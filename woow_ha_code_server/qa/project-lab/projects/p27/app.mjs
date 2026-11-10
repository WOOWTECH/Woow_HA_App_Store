export const meta = {
  id: 'p27', title: 'Release Note Grouper', category: 'Developer tools', version: '1.1.0',
  description: 'Group supplied commit messages into release notes and suggest a release increment from their declared intent.',
  example: { version: '1.5.0', commits: [{ id: 'a1', message: 'feat(search): add saved filters' }, { id: 'b2', message: 'fix: preserve sort order' }, { id: 'c3', message: 'docs: explain keyboard shortcuts' }] }
};
const groupNames = ['Breaking changes', 'Features', 'Fixes', 'Performance', 'Documentation', 'Maintenance', 'Other'];
const escapeMarkdown = text => text.replace(/[\\`*_[\]<>]/g, '\\$&');
export function run(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).some(k => !['version', 'commits'].includes(k))) throw new Error('Input must contain version and commits');
  const { version, commits } = input;
  if (typeof version !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(version)) throw new Error('version must be a release label of 1–64 letters, digits, dots, dashes, or underscores');
  if (!Array.isArray(commits) || commits.length < 1 || commits.length > 500) throw new Error('commits must contain 1–500 entries');
  const buckets = new Map(groupNames.map(n => [n, []])), seen = new Set();
  const counts = { total: commits.length, breaking: 0, features: 0, fixes: 0 };
  let hasPatch = false, characters = 0;
  for (const commit of commits) {
    if (!commit || typeof commit !== 'object' || Array.isArray(commit) || Object.keys(commit).some(k => !['id', 'message'].includes(k)) || typeof commit.id !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9-]{0,39}$/.test(commit.id)) throw new Error('Each commit needs a safe id of 1–40 characters');
    if (seen.has(commit.id)) throw new Error(`Duplicate commit id ${commit.id}`);
    seen.add(commit.id);
    if (typeof commit.message !== 'string' || !commit.message.trim() || commit.message.length > 4000 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(commit.message)) throw new Error('Commit message must contain 1–4000 text characters');
    characters += commit.message.length;
    if (characters > 100000) throw new Error('Combined commit messages exceed 100000 characters');
    const normalized = commit.message.replace(/\r\n/g, '\n');
    const subject = normalized.split('\n')[0].trim();
    if (!subject) throw new Error('Commit subject cannot be blank');
    const match = /^([a-z][a-z0-9-]*)(?:\(([^()]{1,40})\))?(!)?:\s+(.+)$/.exec(subject);
    const type = match?.[1] ?? '', scope = match?.[2] ?? null, description = match?.[4] ?? subject;
    const breaking = Boolean(match?.[3]) || /(?:^|\n)BREAKING[ -]CHANGE:\s*\S/.test(normalized);
    if (type === 'feat') counts.features++;
    if (type === 'fix') counts.fixes++;
    if (type === 'fix' || type === 'perf') hasPatch = true;
    if (breaking) counts.breaking++;
    let category = breaking ? 'Breaking changes' : type === 'feat' ? 'Features' : type === 'fix' ? 'Fixes' : type === 'perf' ? 'Performance' : type === 'docs' ? 'Documentation' : ['chore', 'test', 'build', 'ci', 'refactor', 'style', 'revert'].includes(type) ? 'Maintenance' : 'Other';
    buckets.get(category).push({ id: commit.id, scope, description });
  }
  const groups = [...buckets].filter(([, entries]) => entries.length).map(([category, entries]) => ({ category, entries }));
  const suggestedBump = counts.breaking ? 'major' : counts.features ? 'minor' : hasPatch ? 'patch' : 'none';
  const markdown = `# Release ${escapeMarkdown(version)}\n\n` + groups.map(group => `## ${group.category}\n\n` + group.entries.map(entry => `- ${entry.scope ? `**${escapeMarkdown(entry.scope)}:** ` : ''}${escapeMarkdown(entry.description)} (${entry.id})`).join('\n')).join('\n\n') + '\n';
  return { version, suggestedBump, counts, groups, markdown };
}
