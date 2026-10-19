const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/web/app.js', 'utf8');

function fn(name) {
  const match = new RegExp(`^(?:async )?function ${name}\\(`, 'm').exec(source);
  assert.ok(match, `missing function ${name}`);
  const after = source.indexOf('\n', match.index) + 1;
  const end = /^}\r?$/m.exec(source.slice(after));
  return end ? source.slice(match.index, after + end.index + 1) : source.slice(match.index);
}

function fixture() {
  const nodes = new Map(), pending = [], timers = [], downloads = [];
  const $ = id => {
    if (!nodes.has(id)) nodes.set(id, {
      value: '', checked: false, textContent: '', innerHTML: '', hidden: false,
      style: { display: 'flex' }, classList: { add() {}, remove() {} },
      setAttribute() {}, removeAttribute() {},
      querySelector: () => ({ focus() {} }),
    });
    return nodes.get(id);
  };
  const context = vm.createContext({
    $, URLSearchParams, Promise, console,
    api: path => new Promise((resolve, reject) => pending.push({ path, resolve, reject })),
    _downloadExcelReport: async path => downloads.push(path),
    withBusy: async (_button, _label, work) => work(),
    modalOpened() {}, modalClosed() {}, toast() {},
    ic: () => '', esc: value => String(value || ''),
    fmtNum: value => String(value || 0), fmtTime: () => '',
    setTimeout: callback => { callback(); return timers.length + 1; },
    clearTimeout() {},
  });
  vm.runInContext(`
    let COLLECTION_JOB_ID = 42, COLLECTION_COMMENT_CONTENT_ID = 0;
    let COLLECTION_COMMENT_PAGE = 1, COLLECTION_COMMENT_TIMER = null;
    let COLLECTION_COMMENT_REQUEST = 0;
  `, context);
  for (const name of ['collectionCommentParams', 'collectionCommentMarkup',
    'loadCollectionComments', 'scheduleCollectionCommentFilter',
    'resetCollectionCommentFilters', 'showCollectionComments',
    'exportFilteredCollectionComments']) vm.runInContext(fn(name), context);
  return { context, $, pending, downloads, run: code => vm.runInContext(code, context) };
}

async function run() {
  const f = fixture();
  const opening = f.run('showCollectionComments(7)');
  assert.equal(f.pending.length, 1);
  let query = new URL('http://local/api?' + f.pending[0].path.split('?')[1]).searchParams;
  assert.equal(query.get('content_id'), '7');
  assert.equal(query.get('paginate'), 'true');
  assert.equal(query.get('page_size'), '40');
  f.pending[0].resolve({ items: [{ user_nickname: '用户', text: '线索', source_keyword: '露营', create_time: 1 }], total: 1, page: 1, pages: 1, has_prev: false, has_next: false });
  await opening;
  assert.match(f.$('collection-comments-list').innerHTML, /线索/);

  f.$('collection-comments-scope').value = '';
  f.$('collection-comments-q').value = '重点';
  f.$('collection-comments-region').value = '广东';
  f.$('collection-comments-secuid').value = 'u-1';
  f.$('collection-comments-dedupe').checked = true;
  f.run('scheduleCollectionCommentFilter()');
  assert.equal(f.pending.length, 2);
  query = new URL('http://local/api?' + f.pending[1].path.split('?')[1]).searchParams;
  assert.equal(query.get('q'), '重点');
  assert.equal(query.get('ip_label'), '广东');
  assert.equal(query.get('user_sec_uid'), 'u-1');
  assert.equal(query.get('dedupe_users'), 'true');
  assert.equal(query.get('content_id'), null);
  f.pending[1].resolve({ items: [], total: 0, page: 1, pages: 1, has_prev: false, has_next: false });
  await new Promise(resolve => setImmediate(resolve));

  const exporting = f.run('exportFilteredCollectionComments(null)');
  await exporting;
  query = new URL('http://local/api?' + f.downloads[0].split('?')[1]).searchParams;
  assert.equal(query.get('q'), '重点');
  assert.equal(query.get('paginate'), null);
  assert.equal(query.get('dedupe_users'), 'true');
  console.log('collection comment filters, stale-safe pagination and filtered export passed');
}

run().catch(error => { console.error(error); process.exitCode = 1; });
