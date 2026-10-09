"""Tests of the Lightroom Classic plug-in's Lua code under Lua 5.1 (Lightroom's Lua version).

SelectionsCore.lua is tested directly. ApplySelections.lua is run against a simulated Lightroom SDK
and catalog. Lightroom itself cannot run here, so the SDK calls are checked against these mocks
only; the field test sheet covers a real Lightroom Classic run. Needs the `lupa` package.
"""
import os
import unittest
from pathlib import Path

import helpers  # noqa: F401  (adds the project folder to sys.path)
import app as app_module

try:
    from lupa import lua51
except ImportError:
    lua51 = None

PLUGIN = Path(__file__).resolve().parent.parent / 'lightroom' / 'PhotoSelect.lrplugin'


def selections(rows, exported=None):
    text = app_module.lightroom_selections('/Photos', rows)
    if exported is not None:
        head, rest = text.split('\n', 1)
        parts = head.split('\t')
        parts[2] = str(exported)
        text = '\t'.join(parts) + '\n' + rest
    return text


def row(name, rating, capture='2026-05-01 10:00:00', keywords=('Keep',), folder='/Volumes/Card/DCIM'):
    return {'path': f'{folder}/{name}', 'name': name, 'capture': capture, 'rating': rating,
            'keywords': list(keywords), 'decision': '', 'suggestion': 'Keep'}


@unittest.skipIf(lua51 is None, 'lupa (Lua 5.1) not installed')
class SelectionsCoreTests(unittest.TestCase):
    def setUp(self):
        self.lua = lua51.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(f"package.path = [[{PLUGIN}/?.lua;]] .. package.path")
        self.core = self.lua.eval("require 'SelectionsCore'")
        # always two results, so Python can unpack them the same way whatever Lua returned
        self.parse = self.lua.eval("function(t) local a, b = require('SelectionsCore').parse(t) return a, b end")
        self.match = self.lua.eval("function(i, p) local a, b = require('SelectionsCore').match(i, p) return a, b end")

    def files(self, *texts):
        t = self.lua.table()
        for i, text in enumerate(texts, 1):
            parsed, err = self.parse(text)
            self.assertIsNone(err)
            t[i] = parsed
        return t

    def photo(self, **kw):
        return self.lua.table_from(kw)

    def test_parse_reads_what_photoselect_writes(self):
        parsed, err = self.parse(selections([row('DSC_0001.NEF', 5, keywords=['Keep', 'Liked', 'Burst 007'])]))
        self.assertIsNone(err)
        e = parsed.entries[1]
        self.assertEqual((e.name, e.capture, e.rating, e.path), ('DSC_0001.NEF', '2026-05-01 10:00:00', 5, '/Volumes/Card/DCIM/DSC_0001.NEF'))
        self.assertEqual(list(e.keywords.values()), ['Keep', 'Liked', 'Burst 007'])
        parsed, err = self.parse('something else')
        self.assertIsNone(parsed)
        self.assertIn('not a PhotoSelect', err)

    def test_matching_strategies(self):
        idx = self.core.index(self.files(selections([
            row('DSC_0001.NEF', 3), row('DSC_0002.NEF', 1, capture='2026-05-01 10:00:01'),
            row('DSC_0003.NEF', 2, capture='2026-05-01 10:00:02'), row('DSC_0004.NEF', 2, capture='2026-05-01 10:00:02')])))
        m = lambda **kw: self.match(idx, self.photo(**kw))
        e, how = m(path='/volumes/card/dcim/DSC_0001.NEF')                     # same file (case-insensitive)
        self.assertEqual((e.rating, how), (3, 'path'))
        e, how = m(path='/Pictures/2026/DSC_0002.NEF', fileName='DSC_0002.NEF', capture='2026-05-01 10:00:01')
        self.assertEqual((e.name, how), ('DSC_0002.NEF', 'name'))             # copied on import
        e, how = m(path='/P/Sail-17.NEF', fileName='Sail-17.NEF', preservedFileName='DSC_0001.NEF', capture='2026-05-01 10:00:00')
        self.assertEqual((e.name, how), ('DSC_0001.NEF', 'name'))             # renamed, original name kept
        e, how = m(path='/P/Sail-18.NEF', fileName='Sail-18.NEF', capture='2026-05-01 10:00:01')
        self.assertEqual((e.name, how), ('DSC_0002.NEF', 'time'))             # renamed: unique capture time
        e, how = m(path='/P/Sail-19.NEF', fileName='Sail-19.NEF', capture='2026-05-01 10:00:02')
        self.assertEqual((e, how), (None, 'ambiguous'))                         # two frames in that second
        e, how = m(path='/P/Sail-20.JPG', fileName='Sail-20.JPG', capture='2026-05-01 10:00:01')
        self.assertIsNone(e)                                                    # different file type
        e, how = m(path='/P/x.NEF', fileName='x.NEF', capture='2027-01-01 00:00:00')
        self.assertIsNone(e)

    def test_newer_export_wins(self):
        old = selections([row('DSC_0001.NEF', 1, keywords=['Drop'])], exported=100)
        new = selections([row('DSC_0001.NEF', 3, keywords=['Keep'])], exported=200)
        idx = self.core.index(self.files(new, old))
        e, _ = self.match(idx, self.photo(path='/Volumes/Card/DCIM/DSC_0001.NEF', fileName='DSC_0001.NEF'))
        self.assertEqual(e.rating, 3)
        e, _ = self.match(idx, self.photo(path='/elsewhere/DSC_0001.NEF', fileName='DSC_0001.NEF'))
        self.assertEqual(e.rating, 3)                                           # name only: replaced entry ignored

    def test_plan_keeps_existing_ratings_unless_asked(self):
        idx = self.core.index(self.files(selections([row('a.NEF', 3), row('b.NEF', 1), row('c.NEF', 5)])))
        photos = self.lua.table(self.photo(path='/Volumes/Card/DCIM/a.NEF', rating=0),
                                self.photo(path='/Volumes/Card/DCIM/b.NEF', rating=4),
                                self.photo(path='/Volumes/Card/DCIM/c.NEF', rating=5),
                                self.photo(path='/Volumes/Card/DCIM/z.NEF', fileName='z.NEF', rating=2))
        plan = self.core.plan(idx, photos, False)
        self.assertEqual((plan.matched, plan.notFound, plan.conflicts, plan.unchanged, plan.rated), (3, 1, 1, 1, 1))
        self.assertEqual([plan['items'][i].setRating for i in (1, 2, 3)], [3, None, None])
        plan = self.core.plan(idx, photos, True)
        self.assertEqual([plan['items'][i].setRating for i in (1, 2, 3)], [3, 1, None])
        text = self.core.summary(plan, 4, 3)
        self.assertIn('3 of 4 photos match', text)
        self.assertIn('1 already have a different star rating', text)


@unittest.skipIf(lua51 is None, 'lupa (Lua 5.1) not installed')
class ApplySelectionsTests(unittest.TestCase):
    """Runs Library > Plug-in Extras > Apply PhotoSelect Selections against a simulated catalog."""

    def run_plugin(self, folder, photos, answer='ok', overwrite=False):
        lua = lua51.LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f"package.path = [[{PLUGIN}/?.lua;]] .. package.path")
        lua.execute(f"package.loaded['Config'] = {{ selectionsFolder = [==[{folder}]==] }}")
        lua.globals().LIST_DIR = lambda f: lua.table(*[str(p) for p in sorted(Path(f).iterdir())])
        lua.execute(SDK_MOCK)
        lua.globals().ANSWER, lua.globals().OVERWRITE = answer, overwrite
        for p in photos:
            lua.eval('addPhoto')(lua.table_from(p))
        lua.execute((PLUGIN / 'ApplySelections.lua').read_text())
        return lua

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        (self.folder / 'one.tsv').write_text(selections([
            row('DSC_0001.NEF', 5, keywords=['Keep', 'Liked', 'Burst 001']),
            row('DSC_0002.NEF', 1, capture='2026-05-01 10:00:01', keywords=['Drop', 'Burst 001']),
            row('DSC_0003.NEF', 2, capture='2026-05-01 10:00:05', keywords=['Consider'])]))

    def tearDown(self):
        self.tmp.cleanup()

    def photos(self):
        # imported with Copy into the Lightroom folder structure; the third was already rated 4 stars
        # and carries a PhotoSelect keyword from an earlier run
        return [{'path': '/Pictures/2026/DSC_0001.NEF', 'fileName': 'DSC_0001.NEF', 'time': '2026-05-01 10:00:00', 'rating': 0},
                {'path': '/Pictures/2026/DSC_0002.NEF', 'fileName': 'DSC_0002.NEF', 'time': '2026-05-01 10:00:01'},
                {'path': '/Pictures/2026/DSC_0003.NEF', 'fileName': 'DSC_0003.NEF', 'time': '2026-05-01 10:00:05', 'rating': 4,
                 'oldKeyword': 'Drop'},
                {'path': '/Pictures/2026/OTHER.NEF', 'fileName': 'OTHER.NEF', 'time': '2026-05-02 09:00:00', 'rating': 2}]

    def state(self, lua):
        return {p.fileName: (p.rating, sorted(lua.eval('keywordNames')(p).values())) for p in lua.globals().PHOTOS.values()}

    def test_apply_sets_stars_and_keywords(self):
        lua = self.run_plugin(self.folder, self.photos())
        g = lua.globals()
        self.assertIn('3 of 4 photos match', g.DIALOG_TEXT)
        self.assertIn('1 photos were not found', g.DIALOG_TEXT)
        self.assertEqual(self.state(lua), {
            'DSC_0001.NEF': (5, ['PhotoSelect/Burst 001', 'PhotoSelect/Keep', 'PhotoSelect/Liked']),
            'DSC_0002.NEF': (1, ['PhotoSelect/Burst 001', 'PhotoSelect/Drop']),
            'DSC_0003.NEF': (4, ['PhotoSelect/Consider']),        # existing 4 stars kept; old keyword replaced
            'OTHER.NEF': (2, []),
        })
        self.assertEqual(g.WRITES, 1)
        self.assertIn('2 star ratings set', g.MESSAGE)

    def test_overwrite_existing_ratings_when_ticked(self):
        lua = self.run_plugin(self.folder, self.photos(), overwrite=True)
        self.assertEqual(self.state(lua)['DSC_0003.NEF'][0], 2)

    def test_cancel_changes_nothing(self):
        lua = self.run_plugin(self.folder, self.photos(), answer='cancel')
        self.assertEqual(lua.globals().WRITES, 0)
        self.assertEqual(self.state(lua)['DSC_0001.NEF'], (0, []))

    def test_no_selections_explains_what_to_do(self):
        lua = self.run_plugin(self.folder / 'missing', self.photos())
        self.assertIn('Send to Lightroom', lua.globals().MESSAGE)
        self.assertEqual(lua.globals().WRITES, 0)


SDK_MOCK = r'''
PHOTOS, WRITES, MESSAGE, DIALOG_TEXT = {}, 0, nil, nil
local writing = false
local Keyword = {}
Keyword.__index = Keyword
function Keyword:getName() return self.name end
function Keyword:getParent() return self.parent end
local keywords = {}
local function makeKeyword(name, parent)
  local key = (parent and parent.name .. '/' or '') .. name
  if not keywords[key] then keywords[key] = setmetatable({ name = name, parent = parent }, Keyword) end
  return keywords[key]
end
local Photo = {}
Photo.__index = Photo
function Photo:getRawMetadata(key)
  if key == 'keywords' then return self.keywords end
  error('unexpected getRawMetadata ' .. key)
end
function Photo:setRawMetadata(key, value)
  assert(writing, 'setRawMetadata outside withWriteAccessDo')
  assert(key == 'rating', key)
  self.rating = value
end
function Photo:addKeyword(k)
  assert(writing and getmetatable(k) == Keyword)
  for _, x in ipairs(self.keywords) do if x == k then return end end
  table.insert(self.keywords, k)
end
function Photo:removeKeyword(k)
  assert(writing)
  for i, x in ipairs(self.keywords) do if x == k then table.remove(self.keywords, i) return end end
end
function addPhoto(t)
  local p = setmetatable({ path = t.path, fileName = t.fileName, time = t.time, rating = t.rating, keywords = {} }, Photo)
  if t.oldKeyword then table.insert(p.keywords, makeKeyword(t.oldKeyword, makeKeyword('PhotoSelect'))) end
  table.insert(PHOTOS, p)
end
function keywordNames(p)
  local out = {}
  for _, k in ipairs(p.keywords) do table.insert(out, (k.parent and k.parent.name .. '/' or '') .. k.name) end
  return out
end
local catalog = {}
function catalog:getTargetPhotos() return PHOTOS end
function catalog:batchGetRawMetadata(photos, keys)
  local out = {}
  for _, p in ipairs(photos) do
    out[p] = { path = p.path, dateTimeOriginal = p.time, rating = p.rating }
  end
  return out
end
function catalog:batchGetFormattedMetadata(photos, keys)
  local out = {}
  for _, p in ipairs(photos) do out[p] = { fileName = p.fileName, preservedFileName = nil } end
  return out
end
function catalog:createKeyword(name, synonyms, includeOnExport, parent, returnExisting)
  assert(writing, 'createKeyword outside withWriteAccessDo')
  assert(returnExisting == true and includeOnExport == false)
  return makeKeyword(name, parent)
end
function catalog:withWriteAccessDo(name, fn, opts)
  assert(type(name) == 'string' and opts.timeout)
  WRITES = WRITES + 1
  writing = true
  fn()
  writing = false
end
local modules = {
  LrApplication = { activeCatalog = function() return catalog end },
  LrBinding = { makePropertyTable = function(context) return {} end },
  -- dateTimeOriginal is stored here as the formatted text already; the real SDK returns a number
  LrDate = { timeToUserFormat = function(t, fmt) assert(fmt == '%Y-%m-%d %H:%M:%S') return t end },
  LrDialogs = {
    message = function(title, text, kind) MESSAGE = text end,
    presentModalDialog = function(args)
      assert(args.title and args.actionVerb == 'Apply')
      DIALOG_TEXT = args.contents.items[1].title
      args.contents.bind_to_object.overwrite = OVERWRITE
      return ANSWER
    end,
  },
  LrFileUtils = {
    exists = function(path)
      local f = io.open(path .. '/.', 'r')
      if f then f:close() return 'directory' end
      return false
    end,
    files = function(folder)
      local names = LIST_DIR(folder)
      local i = 0
      return function() i = i + 1 return names[i] end
    end,
    readFile = function(path) local f = assert(io.open(path, 'rb')) local t = f:read('*a') f:close() return t end,
  },
  LrFunctionContext = {
    callWithContext = function(name, fn)
      local failure
      local context = { addFailureHandler = function(self, h) failure = h end }
      local ok, err = pcall(fn, context)
      if not ok then if failure then failure(false, err) end error(err) end
    end,
  },
  LrPathUtils = {
    extension = function(path) return path:match('%.([^%./]+)$') or '' end,
    child = function(a, b) return a .. '/' .. b end,
    getStandardFilePath = function(kind) return '/Users/test' end,
  },
  LrTasks = { startAsyncTask = function(fn) fn() end },
  LrView = {
    bind = function(key) return { bind = key } end,
    osFactory = function()
      local f = {}
      function f:column(t) local items = {} for i, v in ipairs(t) do items[i] = v end t.items = items return t end
      function f:static_text(t) return t end
      function f:checkbox(t) return t end
      function f:control_spacing() return 8 end
      return f
    end,
  },
}
function import(name) return assert(modules[name], 'unknown SDK module ' .. name) end
'''


if __name__ == '__main__':
    unittest.main()
