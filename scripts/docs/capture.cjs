// Captures the user-guide screenshots from a running demo (see demo_server.py and `make docs-screenshots`).
//   NODE_PATH=$(npm root -g) node scripts/docs/capture.cjs <lang> <outDir> [baseUrl]
const { chromium } = require('playwright');
const fs = require('node:fs');

const [lang, outDir, baseUrl = 'http://localhost:4200'] = process.argv.slice(2);
const T = {
  en: { ask: 'Ask', manual: 'User manual', project: 'AirLink X200', q: 'How do I restore the factory settings?',
        research: 'Compare the factory reset and the firmware update procedures of the AirLink X200', note: 'Open questions' },
  it: { ask: 'Chiedi', manual: 'Manuale utente', project: 'AirLink X200', q: 'Come si ripristinano le impostazioni di fabbrica?',
        research: 'Confronta le procedure di ripristino di fabbrica e di aggiornamento firmware di AirLink X200', note: 'Domande aperte' },
}[lang];
const L = (en, it) => (lang === 'it' ? it : en);

(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: lang === 'it' ? 'it-IT' : 'en-US', colorScheme: 'light' });
  await ctx.addInitScript((l) => { try { localStorage.setItem('on.lang', l); localStorage.setItem('on.theme', 'light'); } catch {} }, lang);
  const page = await ctx.newPage();
  const shot = async (name, opts = {}) => {
    await page.waitForTimeout(opts.wait ?? 500);
    await page.screenshot({ path: `${outDir}/${name}.png`, ...(opts.locator ? {} : opts) });
    console.log('shot', name);
  };
  const shotEl = async (name, locator, wait = 500) => { await page.waitForTimeout(wait); await locator.screenshot({ path: `${outDir}/${name}.png` }); console.log('shot', name); };

  // 01 login
  await page.goto(`${baseUrl}/login`, { waitUntil: 'networkidle' });
  await shot('login');
  await page.fill('input[type=email]', 'anna.rossi@example.com');
  await page.fill('input[type=password]', 'correct-horse-battery');
  await page.click('button[type=submit]');
  await page.waitForURL('**/workbench', { timeout: 30000 });

  const step = async (name, fn) => { try { await fn(); } catch (e) { console.error(`STEP ${name} FAILED:`, String(e).split('\n')[0]); } };
  const T2 = {
    en: { workspace: 'Product documentation', firmware: 'Firmware', toggle: (n) => `Toggle ${n}`, nodeActions: 'Node actions', share: 'Share…',
          settings: 'Project settings…', search: 'Search', newNote: 'New note', cancel: 'Cancel', close: 'Close', details: 'Source details',
          deep: 'Deep research', models: 'Models', providers: 'Providers', groups: 'Groups', users: 'Users', theme: 'Choose theme', dark: 'Dark',
          language: 'Choose language', query: 'transmit power', graph: 'Graph' },
    it: { workspace: 'Documentazione di prodotto', firmware: 'Firmware', toggle: (n) => `Espandi o comprimi ${n}`, nodeActions: 'Azioni sul nodo', share: 'Condividi…',
          settings: 'Impostazioni del progetto…', search: 'Cerca', newNote: 'Nuova nota', cancel: 'Annulla', close: 'Chiudi', details: 'Dettagli della fonte',
          deep: 'Ricerca approfondita', models: 'Modelli', providers: 'Provider', groups: 'Gruppi', users: 'Utenti', theme: 'Scegli il tema', dark: 'Scuro',
          language: 'Scegli la lingua', query: 'potenza di trasmissione', graph: 'Grafo' },
  }[lang];

  // 02 workbench: expand the tree, select the manual notebook, ask a question
  await page.getByRole('button', { name: T.project, exact: true }).first().waitFor({ timeout: 20000 });
  await page.getByRole('button', { name: T2.toggle(T.project) }).click();
  await page.getByRole('button', { name: T2.workspace, exact: true }).waitFor();
  await page.getByRole('button', { name: T2.toggle(T2.workspace) }).click();
  await page.getByRole('button', { name: T.manual, exact: true }).click();
  await page.getByRole('button', { name: T2.toggle(T.manual) }).click().catch(() => {});
  await page.waitForTimeout(1500);
  await page.locator('textarea').first().fill(T.q);
  await page.getByRole('button', { name: T.ask, exact: true }).click();
  await page.locator('.cite').first().waitFor({ timeout: 30000 });
  await page.locator('textarea').first().click(); // leave the focus out of the toggles
  await shot('workbench', { wait: 1500 });

  await step('tree-menu', async () => {
    await page.getByRole('button', { name: T.project, exact: true }).first().hover();
    await page.getByRole('button', { name: T2.nodeActions }).first().click();
    await shot('tree-menu');
    await page.keyboard.press('Escape');
  });
  await step('share', async () => {
    await page.getByRole('button', { name: T2.nodeActions }).first().click();
    await page.getByRole('menuitem', { name: T2.share }).click();
    await shot('share-dialog', { wait: 900 });
    await page.getByRole('button', { name: /Close|Chiudi|Cancel|Annulla/ }).first().click();
  });
  await step('project-settings', async () => {
    await page.getByRole('button', { name: T2.nodeActions }).first().click();
    await page.getByRole('menuitem', { name: T2.settings }).click();
    await shot('project-settings', { wait: 900 });
    await page.getByRole('button', { name: /Close|Chiudi|Cancel|Annulla/ }).first().click();
  });
  await step('citation-viewer', async () => {
    await page.locator('.cite').first().click();
    await page.waitForTimeout(2500);
    await shot('viewer', { wait: 1500 });
    await page.getByRole('button', { name: T2.details }).click();
    await shot('source-details', { wait: 1200 });
    await page.getByRole('button', { name: T2.close }).first().click();
    await page.waitForTimeout(800);
  });
  await step('search', async () => {
    await page.locator('mat-button-toggle').filter({ hasText: T2.search }).click();
    await page.locator('app-search-panel input, app-search-panel textarea').first().fill(T2.query);
    await page.keyboard.press('Enter');
    await page.waitForTimeout(1500);
    await shot('search');
    await page.locator('mat-button-toggle').filter({ hasText: 'Chat' }).click();
  });
  await step('notes', async () => {
    await page.getByRole('button', { name: T2.newNote }).click();
    await shot('note-dialog', { wait: 900 });
    await page.getByRole('button', { name: T2.cancel }).click();
  });
  await step('deep-research', async () => {
    await page.getByText(T2.deep, { exact: true }).click();
    await page.locator('textarea').first().fill(T.research);
    await page.getByRole('button', { name: T.ask, exact: true }).click();
    await page.waitForTimeout(6000);
    await shot('deep-research', { wait: 1500 });
  });
  await step('dark', async () => {
    await page.getByRole('button', { name: T2.theme }).click();
    await page.getByRole('menuitem', { name: T2.dark }).click();
    await shot('workbench-dark', { wait: 1000 });
    await page.getByRole('button', { name: T2.theme }).click();
    await page.getByRole('menuitem', { name: /Light|Chiaro/ }).click();
  });
  await step('language', async () => {
    await page.getByRole('button', { name: T2.language }).click();
    await shot('language-menu');
    await page.keyboard.press('Escape');
  });

  const goto = async (path, wait = 1500) => { await page.goto(`${baseUrl}${path}`, { waitUntil: 'networkidle' }); await page.mouse.move(700, 600); await page.waitForTimeout(wait); };
  await step('upload', async () => { await goto('/upload'); await shot('upload'); });
  await step('wiki', async () => {
    await goto('/wiki', 2500);
    await shot('wiki');
    await page.getByRole('button', { name: T2.graph, exact: true }).click().catch(() => {});
    await shot('wiki-graph', { wait: 2500 });
    await page.getByRole('button', { name: new RegExp(L('AirLink X200', 'AirLink X200')) }).first().click().catch(() => {});
    await page.getByRole('button', { name: L('Page', 'Pagina'), exact: true }).click().catch(() => {});
    await shot('wiki-page', { wait: 2500 });
  });
  await step('history', async () => { await goto('/history'); await shot('history'); });
  await step('status', async () => { await goto('/status', 2500); await shot('status', { fullPage: true }); });
  await step('settings-models', async () => { await goto('/settings/models', 2500); await shot('settings-models', { fullPage: true }); });
  await step('settings-providers', async () => { await goto('/settings/providers', 2000); await shot('settings-providers'); });
  await step('settings-groups', async () => { await goto('/settings/groups'); await shot('settings-groups'); });
  await step('settings-users', async () => { await goto('/settings/users'); await shot('settings-users'); });

  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
