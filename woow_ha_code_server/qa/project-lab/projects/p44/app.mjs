export const meta = {
  id: 'p44', title: 'Offline RSS feed generator', category: 'Publishing',
  description: 'Build escaped RSS 2.0 XML from validated channel and article data.',
  version: '1.1.0',
  example: { channel: { title: 'Studio & Notes', link: 'https://example.invalid', description: 'Offline project updates' },
    items: [{ title: 'Release <one>', link: 'https://example.invalid/releases/one', description: 'Small & useful tools.', publishedAt: '2024-01-01T00:00:00Z' }] }
};
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
function check(ok, message) { if (!ok) throw new Error(message); }
function string(value, name, max, empty = false) {
  check(typeof value === 'string' && value.length <= max && (empty || value.trim().length > 0), name + ' must be a string of at most ' + max + ' characters');
  for (const ch of value) {
    const c = ch.codePointAt(0);
    check(c === 9 || c === 10 || c === 13 || (c >= 32 && c <= 0xd7ff) || (c >= 0xe000 && c <= 0xfffd) || (c >= 0x10000 && c <= 0x10ffff), name + ' contains invalid XML characters');
  }
  return value;
}
function link(value, name) {
  string(value, name, 2048);
  let url;
  try { url = new URL(value); } catch { throw new Error(name + ' must be an absolute HTTP(S) URL'); }
  check(['http:', 'https:'].includes(url.protocol) && !url.username && !url.password && !/\s/.test(value), name + ' must be HTTP(S), without credentials or whitespace');
  return value;
}
function date(value) {
  check(typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value), 'publishedAt must be UTC YYYY-MM-DDTHH:mm:ssZ');
  const ms = Date.parse(value);
  check(Number.isFinite(ms) && new Date(ms).toISOString() === value.replace('Z', '.000Z'), 'publishedAt must be a real calendar date');
  return ms;
}
const escape = value => value.replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[ch]);
export function run(input) {
  check(object(input) && object(input.channel), 'Input requires channel object');
  const c = input.channel;
  const title = string(c.title, 'channel.title', 500);
  const channelLink = link(c.link, 'channel.link');
  const description = string(c.description, 'channel.description', 5000, true);
  const language = c.language ?? 'en';
  check(typeof language === 'string' && language.length <= 35 && /^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$/.test(language), 'language must be a language tag');
  check(Array.isArray(input.items) && input.items.length <= 100, 'items must be an array of at most 100 entries');
  const { maxItems } = input;
  check(maxItems === undefined || (Number.isInteger(maxItems) && maxItems >= 1 && maxItems <= 100), 'maxItems must be an integer from 1 to 100');
  const guids = new Set();
  const items = input.items.map((item, index) => {
    check(object(item), 'Each item must be an object');
    const title = string(item.title, 'item.title', 500);
    const itemLink = link(item.link, 'item.link');
    const guid = string(item.guid ?? itemLink, 'item.guid', 2048);
    check(!guids.has(guid), 'Duplicate item guid: ' + guid); guids.add(guid);
    return { title, link: itemLink, guid, description: string(item.description ?? '', 'item.description', 5000, true),
      publishedAt: item.publishedAt, ms: date(item.publishedAt), index };
  }).sort((a, b) => b.ms - a.ms || a.index - b.index).slice(0, maxItems);
  const lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0">', '  <channel>',
    '    <title>' + escape(title) + '</title>', '    <link>' + escape(channelLink) + '</link>',
    '    <description>' + escape(description) + '</description>', '    <language>' + escape(language) + '</language>'];
  for (const item of items) lines.push('    <item>',
    '      <title>' + escape(item.title) + '</title>',
    '      <link>' + escape(item.link) + '</link>',
    '      <guid isPermaLink="false">' + escape(item.guid) + '</guid>',
    '      <description>' + escape(item.description) + '</description>',
    '      <pubDate>' + new Date(item.ms).toUTCString() + '</pubDate>', '    </item>');
  lines.push('  </channel>', '</rss>');
  return { xml: lines.join('\n') + '\n', itemCount: items.length, latestPublishedAt: items[0]?.publishedAt ?? null };
}
