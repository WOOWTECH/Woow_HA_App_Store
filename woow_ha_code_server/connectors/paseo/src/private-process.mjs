// Trusted build/runtime entrypoint only; no request can select this executable.
// Set a private umask in the child without changing the parent VS Code process.
import { pathToFileURL } from 'node:url';
process.umask(0o077);
process.argv = [process.execPath, ...process.argv.slice(2)];
await import(pathToFileURL(process.argv[1]).href);
