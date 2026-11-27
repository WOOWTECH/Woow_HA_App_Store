import { readFileSync } from "node:fs";
import { open, readFile, stat, unlink, utimes } from "node:fs/promises";
import { ensurePrivateDirectory } from "./private-files.js";
import { join } from "node:path";
import { uptime } from "node:os";
import { getHostName } from "./host-name.js";
import { z } from "zod";
export const pidLockInfoSchema = z.object({
    pid: z.number().int().positive(),
    startedAt: z.string(),
    hostname: z.string(),
    uid: z.number(),
    listen: z.string().nullable(),
    serverId: z.string().nullable().optional(),
    desktopManaged: z.boolean().optional(),
    heartbeat: z.literal(true).optional(),
    bootId: z.string().optional(),
});
function parsePidLockInfo(raw) {
    const result = pidLockInfoSchema.safeParse(raw);
    return result.success ? result.data : null;
}
function isErrnoException(err) {
    return err instanceof Error && "code" in err;
}
// The field is assigned explicitly rather than declared as a constructor parameter property:
// the terminal worker loads this module under --experimental-strip-types, which cannot emit
// the assignment a parameter property implies.
export class PidLockError extends Error {
    constructor(message, existingLock) {
        super(message);
        this.name = "PidLockError";
        this.existingLock = existingLock;
    }
}
const PID_LOCK_HEARTBEAT_INTERVAL_MS = 30000;
const PID_LOCK_READ_RETRY_ATTEMPTS = 10;
const PID_LOCK_READ_RETRY_DELAY_MS = 50;
function isPidRunning(pid) {
    try {
        process.kill(pid, 0);
        return true;
    }
    catch (error) {
        return isErrnoException(error) && error.code === "EPERM";
    }
}
// `uptime()` reports whole seconds on some platforms, so the derived boot instant carries
// about a second of error. This covers that resolution and nothing more: every extra second
// is a window in which a lock written just before a reboot still reads as current.
const BOOT_INSTANT_TOLERANCE_MS = 5000;
function precedesThisBoot(startedAt) {
    const stamped = Date.parse(startedAt);
    if (Number.isNaN(stamped))
        return false;
    return stamped < Date.now() - uptime() * 1000 - BOOT_INSTANT_TOLERANCE_MS;
}
let cachedBootId;
// Linux names each boot. The wall-clock boot instant is not enough there: a VM paused while
// its host sleeps keeps its uptime, so after it resumes the instant lands after locks its
// running supervisor wrote.
export function currentBootId() {
    if (cachedBootId === undefined) {
        try {
            cachedBootId = readFileSync("/proc/sys/kernel/random/boot_id", "utf-8").trim() || null;
        }
        catch {
            cachedBootId = null;
        }
    }
    return cachedBootId;
}
/**
 * Whether a record stamped with `startedAt` (and, on Linux, `bootId`) was written during the
 * current boot. Daemon locks and terminal worker records share this rule.
 */
export function writtenDuringThisBoot(stamp) {
    const thisBoot = currentBootId();
    if (stamp.bootId && thisBoot)
        return stamp.bootId === thisBoot;
    return !precedesThisBoot(stamp.startedAt);
}
/**
 * Whether the process that wrote this lock is still running.
 *
 * A PID alone does not identify the supervisor: the operating system hands the number to
 * something else once the supervisor is gone, and a reboot reassigns it freely. A process
 * cannot predate the boot it runs under, so a lock written during another boot is abandoned
 * however alive its PID looks.
 */
export function isPidLockOwnerRunning(lock) {
    if (!writtenDuringThisBoot(lock))
        return false;
    return isPidRunning(lock.pid);
}
function getPidFilePath(paseoHome) {
    return join(paseoHome, "paseo.pid");
}
async function touchPidLockFile(pidPath) {
    const now = new Date();
    await utimes(pidPath, now, now);
}
async function readPidLock(pidPath) {
    let lastError;
    let empty = false;
    for (let attempt = 0; attempt < PID_LOCK_READ_RETRY_ATTEMPTS; attempt++) {
        try {
            const content = await readFile(pidPath, "utf-8");
            empty = content === "";
            if (!empty) {
                const lock = parsePidLockInfo(JSON.parse(content));
                if (lock)
                    return lock;
                lastError = new Error("Invalid lock shape");
            }
        }
        catch (error) {
            if (isErrnoException(error) && error.code === "ENOENT")
                return null;
            empty = false;
            lastError = error;
        }
        await new Promise((resolve) => setTimeout(resolve, PID_LOCK_READ_RETRY_DELAY_MS));
    }
    // A supervisor writes its lock right after creating the file, so a file still empty
    // after the retries was abandoned in between and names no owner.
    if (empty)
        return null;
    throw Object.assign(new PidLockError(`Cannot read daemon state at ${pidPath}: ${String(lastError)}`), { code: "DAEMON_STATE_READ_FAILED" });
}
function resolveOwnerPid(ownerPid) {
    if (typeof ownerPid === "number" && Number.isInteger(ownerPid) && ownerPid > 0) {
        return ownerPid;
    }
    return process.pid;
}
export function isSamePidLock(left, right) {
    return left.pid === right.pid && left.startedAt === right.startedAt;
}
function createLockHeldError(lock) {
    return new PidLockError(`Another Paseo daemon is already running (PID ${lock.pid}, started ${lock.startedAt})`, lock);
}
async function clearExistingPidLock(pidPath, existingLock, lockOwnerPid) {
    const lockOwnerRunning = isPidLockOwnerRunning(existingLock);
    if (existingLock.pid === lockOwnerPid && lockOwnerRunning) {
        await touchPidLockFile(pidPath);
        return "already_owned";
    }
    if (lockOwnerRunning)
        throw createLockHeldError(existingLock);
    const confirmedLock = await readPidLock(pidPath);
    if (!confirmedLock ||
        !isSamePidLock(existingLock, confirmedLock) ||
        isPidLockOwnerRunning(confirmedLock)) {
        throw new PidLockError("PID lock changed while checking whether it was abandoned");
    }
    await unlink(pidPath).catch(() => { });
    return "cleared";
}
async function removeEmptyPidLock(pidPath) {
    try {
        if ((await stat(pidPath)).size === 0)
            await unlink(pidPath);
    }
    catch (error) {
        if (!isErrnoException(error) || error.code !== "ENOENT")
            throw error;
    }
}
async function writeNewPidLock(pidPath, lockInfo) {
    let fd;
    try {
        fd = await open(pidPath, "wx");
        await fd.write(JSON.stringify(lockInfo));
    }
    catch (error) {
        if (!isErrnoException(error) || error.code !== "EEXIST") {
            throw error;
        }
        const raceLock = await readPidLock(pidPath);
        if (raceLock) {
            throw new PidLockError(`Another Paseo daemon is already running (PID ${raceLock.pid})`, raceLock);
        }
        throw new PidLockError("Failed to acquire PID lock due to race condition");
    }
    finally {
        await fd?.close();
    }
}
export async function acquirePidLock(paseoHome, listen, options) {
    const pidPath = getPidFilePath(paseoHome);
    ensurePrivateDirectory(paseoHome);
    // Try to read existing lock
    const existingLock = await readPidLock(pidPath);
    // Check if existing lock is stale
    const lockOwnerPid = resolveOwnerPid(options?.ownerPid);
    if (existingLock) {
        const result = await clearExistingPidLock(pidPath, existingLock, lockOwnerPid);
        if (result === "already_owned") {
            return;
        }
    }
    else {
        await removeEmptyPidLock(pidPath);
    }
    // Create new lock with exclusive flag
    const bootId = currentBootId();
    const lockInfo = {
        pid: lockOwnerPid,
        startedAt: new Date().toISOString(),
        hostname: getHostName(),
        uid: process.getuid?.() ?? 0,
        listen,
        heartbeat: true,
        ...(bootId ? { bootId } : {}),
        ...(process.env.PASEO_DESKTOP_MANAGED === "1" ? { desktopManaged: true } : {}),
    };
    await writeNewPidLock(pidPath, lockInfo);
}
export async function refreshPidLock(paseoHome, options) {
    const pidPath = getPidFilePath(paseoHome);
    const lockOwnerPid = resolveOwnerPid(options?.ownerPid);
    let fd;
    try {
        fd = await open(pidPath, "r+");
    }
    catch (error) {
        if (isErrnoException(error) && error.code === "ENOENT") {
            throw new PidLockError("Cannot refresh PID lock: lock file is missing");
        }
        throw error;
    }
    try {
        const lock = await readPidLockFromHandleWithRetry(fd);
        if (!lock) {
            throw new PidLockError("Cannot refresh PID lock: invalid lock file");
        }
        if (lock.pid !== lockOwnerPid) {
            throw new PidLockError(`Cannot refresh PID lock owned by PID ${lock.pid}`, lock);
        }
        const now = new Date();
        await fd.utimes(now, now);
    }
    finally {
        await fd.close();
    }
}
async function readPidLockFromHandle(fd) {
    try {
        const { size } = await fd.stat();
        if (size === 0) {
            return null;
        }
        const content = Buffer.alloc(size);
        const { bytesRead } = await fd.read(content, 0, size, 0);
        return parsePidLockInfo(JSON.parse(content.subarray(0, bytesRead).toString("utf-8")));
    }
    catch {
        return null;
    }
}
async function readPidLockFromHandleWithRetry(fd) {
    for (let attempt = 0; attempt < PID_LOCK_READ_RETRY_ATTEMPTS; attempt += 1) {
        const lock = await readPidLockFromHandle(fd);
        if (lock) {
            return lock;
        }
        if (attempt < PID_LOCK_READ_RETRY_ATTEMPTS - 1) {
            await new Promise((resolve) => setTimeout(resolve, PID_LOCK_READ_RETRY_DELAY_MS));
        }
    }
    return null;
}
export function startPidLockHeartbeat(paseoHome, options) {
    const intervalMs = options?.intervalMs ?? PID_LOCK_HEARTBEAT_INTERVAL_MS;
    let refreshing = false;
    const timer = setInterval(() => {
        if (refreshing) {
            return;
        }
        refreshing = true;
        refreshPidLock(paseoHome, { ownerPid: options?.ownerPid })
            .catch((error) => {
            if (options?.onError) {
                options.onError(error);
                return;
            }
            const message = error instanceof Error ? error.message : String(error);
            process.stderr.write(`PID lock heartbeat failed: ${message}\n`);
        })
            .finally(() => {
            refreshing = false;
        });
    }, intervalMs);
    timer.unref();
    return () => clearInterval(timer);
}
export async function updatePidLock(paseoHome, patch, options) {
    const pidPath = getPidFilePath(paseoHome);
    const lockOwnerPid = resolveOwnerPid(options?.ownerPid);
    const fd = await open(pidPath, "r+");
    try {
        const existingLock = await readPidLockFromHandleWithRetry(fd);
        if (!existingLock) {
            throw new PidLockError("Cannot update PID lock: invalid lock file");
        }
        if (existingLock.pid !== lockOwnerPid) {
            throw new PidLockError(`Cannot update PID lock owned by PID ${existingLock.pid}`, existingLock);
        }
        const updatedLock = {
            ...existingLock,
            ...patch,
        };
        await fd.truncate(0);
        await fd.writeFile(JSON.stringify(updatedLock));
    }
    finally {
        await fd.close();
    }
}
export async function releasePidLock(paseoHome, options) {
    const pidPath = getPidFilePath(paseoHome);
    const lockOwnerPid = resolveOwnerPid(options?.ownerPid);
    try {
        // Only remove if it's our lock
        const content = await readFile(pidPath, "utf-8");
        const lock = parsePidLockInfo(JSON.parse(content));
        if (lock?.pid === lockOwnerPid &&
            (options?.startedAt === undefined || lock.startedAt === options.startedAt)) {
            await unlink(pidPath);
        }
    }
    catch {
        // Ignore errors - lock may already be gone
    }
}
export async function getPidLockInfo(paseoHome) {
    const pidPath = getPidFilePath(paseoHome);
    return readPidLock(pidPath);
}
export async function isLocked(paseoHome) {
    const info = await getPidLockInfo(paseoHome);
    if (!info) {
        return { locked: false };
    }
    if (!isPidLockOwnerRunning(info)) {
        return { locked: false, info };
    }
    return { locked: true, info };
}
//# sourceMappingURL=pid-lock.js.map