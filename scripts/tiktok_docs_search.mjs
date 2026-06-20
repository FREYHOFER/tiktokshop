import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const startUrl = process.env.TIKTOK_DOCS_URL || 'https://partner.tiktokshop.com/doc';
const rawTerms = process.env.SEARCH_TERMS || 'mission,missions,task,tasks,campaign,campaigns,affiliate,creator,creator mission,seller mission';
const terms = rawTerms.split(',').map((term) => term.trim()).filter(Boolean);
const outputDir = process.env.OUTPUT_DIR || 'outputs/tiktok_docs_search';
const maxCapturedResponseChars = 250000;

function normalize(text) {
  return String(text || '').replace(/\s+/g, ' ').trim();
}

function snippetsFor(text, term) {
  const lower = text.toLowerCase();
  const target = term.toLowerCase();
  const snippets = [];
  let pos = lower.indexOf(target);
  while (pos !== -1 && snippets.length < 10) {
    const start = Math.max(0, pos - 180);
    const end = Math.min(text.length, pos + target.length + 220);
    snippets.push(normalize(text.slice(start, end)));
    pos = lower.indexOf(target, pos + target.length);
  }
  return snippets;
}

function collectMatches(label, url, text) {
  const matches = [];
  for (const term of terms) {
    const snippets = snippetsFor(text, term);
    if (snippets.length) {
      matches.push({ term, count: snippets.length, snippets });
    }
  }
  return matches.length ? { label, url, matches } : null;
}

await fs.mkdir(outputDir, { recursive: true });

const captured = [];
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });

page.on('response', async (response) => {
  const url = response.url();
  const contentType = response.headers()['content-type'] || '';
  if (!/(json|javascript|text|html)/i.test(contentType)) return;
  try {
    const body = await response.text();
    captured.push({
      url,
      status: response.status(),
      contentType,
      text: body.slice(0, maxCapturedResponseChars),
    });
  } catch {
    // Some responses cannot be read after redirects or due to browser internals.
  }
});

await page.goto(startUrl, { waitUntil: 'networkidle', timeout: 90000 });
await page.waitForTimeout(5000);

const pageTitle = await page.title().catch(() => '');
const bodyText = await page.locator('body').innerText({ timeout: 15000 }).catch(() => '');
await page.screenshot({ path: path.join(outputDir, 'tiktok_docs_page.png'), fullPage: true }).catch(() => {});

const searchResults = [];
const pageMatch = collectMatches('rendered_page_text', page.url(), bodyText);
if (pageMatch) searchResults.push(pageMatch);

for (const item of captured) {
  const match = collectMatches('captured_response', item.url, item.text);
  if (match) {
    searchResults.push({
      ...match,
      status: item.status,
      contentType: item.contentType,
    });
  }
}

const report = {
  generatedAt: new Date().toISOString(),
  startUrl,
  finalUrl: page.url(),
  pageTitle,
  terms,
  capturedResponseCount: captured.length,
  matchCount: searchResults.length,
  renderedTextSample: normalize(bodyText).slice(0, 4000),
  matches: searchResults,
};

await fs.writeFile(path.join(outputDir, 'report.json'), JSON.stringify(report, null, 2), 'utf8');
await fs.writeFile(
  path.join(outputDir, 'captured_urls.txt'),
  captured.map((item) => `${item.status} ${item.contentType} ${item.url}`).join('\n') + '\n',
  'utf8',
);

console.log(`TikTok docs URL: ${page.url()}`);
console.log(`Captured responses: ${captured.length}`);
console.log(`Matches: ${searchResults.length}`);
for (const match of searchResults.slice(0, 20)) {
  console.log(`- ${match.label}: ${match.url}`);
  for (const item of match.matches.slice(0, 5)) {
    console.log(`  ${item.term}: ${item.count}`);
  }
}

await browser.close();
