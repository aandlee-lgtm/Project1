--[[ Lightroom operations shared by the menu command (ApplySelections.lua) and the background task
that applies stars to photos imported from PhotoSelect (Init.lua). The decisions themselves
(parsing, matching, planning) are in SelectionsCore.lua. ]]
local LrApplication = import 'LrApplication'
local LrDate = import 'LrDate'
local LrDialogs = import 'LrDialogs'
local LrFileUtils = import 'LrFileUtils'
local LrPathUtils = import 'LrPathUtils'
local LrTasks = import 'LrTasks'

local Core = require 'SelectionsCore'
local Ops = { stopped = false }
Ops.TITLE = 'Apply PhotoSelect Selections'
Ops.PENDING = 'pending.import'          -- photos PhotoSelect handed to Lightroom's Import window
local PENDING_HOURS = 3

function Ops.selectionsFolder()
  local ok, config = pcall(require, 'Config')
  if ok and type(config) == 'table' and config.selectionsFolder then
    return config.selectionsFolder
  end
  return LrPathUtils.child(LrPathUtils.getStandardFilePath('home'), 'Library/Application Support/PhotoSelect/Lightroom')
end

function Ops.loadSelections(folder)
  local files = {}
  if LrFileUtils.exists(folder) ~= 'directory' then
    return files
  end
  for path in LrFileUtils.files(folder) do
    if LrPathUtils.extension(path) == 'tsv' then
      local parsed = Core.parse(LrFileUtils.readFile(path))
      if parsed then
        files[#files + 1] = parsed
      end
    end
  end
  return files
end

function Ops.describePhotos(catalog, photos)
  local raw = catalog:batchGetRawMetadata(photos, { 'path', 'dateTimeOriginal', 'rating' })
  local formatted = catalog:batchGetFormattedMetadata(photos, { 'fileName', 'preservedFileName' })
  local out = {}
  for _, photo in ipairs(photos) do
    local r, f = raw[photo] or {}, formatted[photo] or {}
    local capture = ''
    if r.dateTimeOriginal then
      capture = LrDate.timeToUserFormat(r.dateTimeOriginal, '%Y-%m-%d %H:%M:%S')
    end
    out[#out + 1] = {
      photo = photo, path = r.path, fileName = f.fileName, preservedFileName = f.preservedFileName,
      capture = capture, rating = r.rating,
    }
  end
  return out
end

Ops.FROM = 'From PhotoSelect'              -- keyword on every photo PhotoSelect rated (used by the Smart Collections)
Ops.SET = 'PhotoSelect'                   -- collection set holding the Smart Collections
-- Smart Collections, in the order the owner reviews them: rescue drops, confirm keeps, decide the rest.
Ops.COLLECTIONS = {
  { name = '1 Rescue', rating = 1 },
  { name = '2 Confirm', rating = 3 },
  { name = '3 Decide', rating = 2 },
  { name = 'Liked', rating = 5 },
  { name = 'Borderline', keyword = 'Borderline' },
}

function Ops.apply(catalog, plan)
  catalog:withWriteAccessDo(Ops.TITLE, function()
    local parent = catalog:createKeyword('PhotoSelect', {}, false, nil, true)
    local made = {}
    local function keyword(name)
      if not made[name] then
        made[name] = catalog:createKeyword(name, {}, false, parent, true)
      end
      return made[name]
    end
    for _, item in ipairs(plan.items) do
      local photo = item.photo.photo
      -- replace keywords from an earlier run so a changed decision does not leave the old one behind
      for _, k in ipairs(photo:getRawMetadata('keywords') or {}) do
        local p = k:getParent()
        if p and p:getName() == 'PhotoSelect' and p:getParent() == nil then
          photo:removeKeyword(k)
        end
      end
      for _, name in ipairs(item.entry.keywords) do
        photo:addKeyword(keyword(name))
      end
      photo:addKeyword(keyword(Ops.FROM))
      if item.setRating then
        photo:setRawMetadata('rating', item.setRating)
      end
    end
  end, { timeout = 60 })
  LrTasks.pcall(Ops.ensureCollections, catalog)
  LrTasks.pcall(Ops.track, Ops.selectionsFolder(), plan)
end

--[[ The "PhotoSelect" collection set with one Smart Collection per review step (see Ops.COLLECTIONS).
Each holds the photos PhotoSelect rated (keyword "From PhotoSelect") that now have that many stars, so
a photo moves between them as its stars change in Lightroom. Made once; existing ones are kept. ]]
local collectionsMade = false
function Ops.ensureCollections(catalog)
  if collectionsMade then return end
  catalog:withWriteAccessDo('PhotoSelect Smart Collections', function()
    local set = catalog:createCollectionSet(Ops.SET, nil, true)
    for _, c in ipairs(Ops.COLLECTIONS) do
      local rule = c.rating and { criteria = 'rating', operation = '==', value = c.rating }
        or { criteria = 'keywords', operation = 'words', value = c.keyword }
      catalog:createSmartCollection(c.name, {
        combine = 'intersect',
        rule,
        { criteria = 'keywords', operation = 'all', value = Ops.FROM },
      }, set, true)
    end
  end, { timeout = 30 })
  collectionsMade = true
end

local function unixNow()
  return LrDate.currentTime() + 978307200   -- Lightroom counts seconds from 2001-01-01 UTC
end
Ops.unixNow = unixNow

Ops.VERSION = '1.6.0'
Ops.STATUS = 'plugin-status.txt'          -- read by PhotoSelect: is the plug-in running, and what did it do
Ops.APPLIED = 'applied.txt'               -- photos already rated automatically (never twice)
Ops.TRACKED = 'tracked.txt'               -- photos PhotoSelect rated: Lightroom id, last stars seen, PhotoSelect path
Ops.CHANGES = 'lightroom-changes.tsv'     -- star changes made in Lightroom, read (and removed) by PhotoSelect
local TRACK_DAYS = 90                     -- star changes are reported for photos rated in the last 90 days
local AUTO_DAYS = 14                      -- selections sent within this many days are applied automatically

local function readLines(path)
  if LrFileUtils.exists(path) ~= 'file' then return {} end
  return Core.split(string.gsub(LrFileUtils.readFile(path) or '', '\r\n', '\n'), '\n')
end

local function writeFile(path, text, mode)
  local f = io.open(path, mode or 'w')
  if f then
    f:write(text)
    f:close()
  end
end

local applied, started = nil, nil
local status = { checked = 0, appliedAt = 0, appliedCount = 0, pending = 0 }

local function appliedSet(folder)
  if not applied then
    applied = {}
    for _, line in ipairs(readLines(LrPathUtils.child(folder, Ops.APPLIED))) do
      if line ~= '' then applied[line] = true end
    end
  end
  return applied
end

local function key(source, entry)
  return string.format('%.3f', source.exported) .. '\t' .. string.lower(entry.path)
end

-- Report that the plug-in is running (PhotoSelect shows this in its Lightroom window).
function Ops.writeStatus(folder)
  if LrFileUtils.exists(folder) ~= 'directory' then return end
  started = started or unixNow()
  writeFile(LrPathUtils.child(folder, Ops.STATUS), table.concat({
    'version\t' .. Ops.VERSION,
    string.format('started\t%.0f', started),
    string.format('checked\t%.0f', unixNow()),
    string.format('applied_at\t%.0f', status.appliedAt),
    'applied_count\t' .. status.appliedCount,
    'waiting\t' .. status.pending,
  }, '\n') .. '\n')
end

--[[ One pass of the background task. Applies stars and keywords to photos that are in the catalog and
have PhotoSelect selections not yet applied: those handed to Lightroom's Import window ("Open in
Lightroom Import", pending.import, checked every pass) and those in selections sent with "Send to
Lightroom" in the last AUTO_DAYS days with automatic rating on (looked up by capture date every
`slow`-th pass, which also finds photos imported with Copy, renamed or as DNG). Each photo is rated
once; stars already set in Lightroom are kept. Returns the number of photos updated. ]]
function Ops.autoApply(round, slow)
  slow = slow or 8
  local folder = Ops.selectionsFolder()
  if LrFileUtils.exists(folder) ~= 'directory' then return 0 end
  local now = unixNow()
  local done = appliedSet(folder)
  local sources, fast = {}, nil
  local pendingPath = LrPathUtils.child(folder, Ops.PENDING)
  if LrFileUtils.exists(pendingPath) == 'file' then
    local pending = Core.parse(LrFileUtils.readFile(pendingPath))
    if pending and pending.exported + PENDING_HOURS * 3600 >= now then
      fast = pending
      sources[#sources + 1] = pending
    else
      LrFileUtils.delete(pendingPath)
    end
  end
  for _, f in ipairs(Ops.loadSelections(folder)) do
    if f.auto and f.exported + AUTO_DAYS * 86400 >= now then
      sources[#sources + 1] = f
    end
  end
  -- what is still waiting to be applied
  local waiting, waitingSources = 0, {}
  for _, src in ipairs(sources) do
    local open = {}
    for _, e in ipairs(src.entries) do
      if not done[key(src, e)] then open[#open + 1] = e end
    end
    waiting = waiting + #open
    if #open > 0 then waitingSources[#waitingSources + 1] = { src = src, open = open } end
  end
  status.pending = waiting
  if waiting == 0 then
    if fast then LrFileUtils.delete(pendingPath) end
    return 0
  end
  local catalog = LrApplication.activeCatalog()
  local candidates, seen = {}, {}
  local function add(photo)
    if photo and not seen[photo] then
      seen[photo] = true
      candidates[#candidates + 1] = photo
    end
  end
  for _, ws in ipairs(waitingSources) do
    if ws.src == fast then
      for _, e in ipairs(ws.open) do add(catalog:findPhotoByPath(e.path)) end
    end
    if round % slow == 0 then
      -- photos captured on the days these selections cover: one catalog query per selections file
      local first, last
      for _, e in ipairs(ws.open) do
        local day = string.sub(e.capture or '', 1, 10)
        if day ~= '' then
          if not first or day < first then first = day end
          if not last or day > last then last = day end
        end
      end
      if first then
        local ok, found = pcall(function()
          return catalog:findPhotos { searchDesc = { criteria = 'captureTime', operation = 'in', value = first, value2 = last } }
        end)
        for _, p in ipairs(ok and found or {}) do add(p) end
      end
    end
  end
  if #candidates == 0 then return 0 end
  local described = Ops.describePhotos(catalog, candidates)
  -- newest selections first; a photo is updated once per pass, and older selections for the same
  -- photo are marked done rather than applied over the newer ones
  table.sort(waitingSources, function(a, b) return a.src.exported > b.src.exported end)
  local fresh, keys, usedPhoto = { items = {}, rated = 0 }, {}, {}
  for _, ws in ipairs(waitingSources) do
    local idx = Core.index({ { exported = ws.src.exported, entries = ws.open } })
    for _, item in ipairs(Core.plan(idx, described, false).items) do
      local k = key(ws.src, item.entry)
      if not done[k] and not keys[k] then
        keys[k] = true
        if not usedPhoto[item.photo.photo] then
          usedPhoto[item.photo.photo] = true
          fresh.items[#fresh.items + 1] = item
          if item.setRating then fresh.rated = fresh.rated + 1 end
        end
      end
    end
  end
  if next(keys) == nil then return 0 end
  if #fresh.items > 0 then Ops.apply(catalog, fresh) end
  local lines = {}
  for k in pairs(keys) do
    done[k] = true
    lines[#lines + 1] = k
  end
  writeFile(LrPathUtils.child(folder, Ops.APPLIED), table.concat(lines, '\n') .. '\n', 'a')
  if fast then
    local left = false
    for _, e in ipairs(fast.entries) do
      if not done[key(fast, e)] then left = true break end
    end
    if not left then LrFileUtils.delete(pendingPath) end
  end
  status.appliedAt, status.appliedCount = unixNow(), #fresh.items
  status.pending = math.max(0, waiting - #lines)
  Ops.writeStatus(folder)
  if #fresh.items > 0 and LrDialogs.showBezel then
    LrDialogs.showBezel(string.format('PhotoSelect: stars applied to %d imported photos', #fresh.items), 4)
  end
  return #fresh.items
end

--[[ Changes flow back (1.6): remember the stars each photo had after PhotoSelect rated it, then report
star changes made in Lightroom to PhotoSelect, which updates its decision to match. ]]
local tracked = nil   -- [localId] = { rating =, at =, path = }

local function trackedSet(folder)
  if not tracked then
    tracked = {}
    for _, line in ipairs(readLines(LrPathUtils.child(folder, Ops.TRACKED))) do
      local id, rating, at, path = string.match(line, '^(%d+)\t(%d)\t([%d%.]+)\t(.+)$')
      if id then tracked[tonumber(id)] = { rating = tonumber(rating), at = tonumber(at), path = path } end
    end
  end
  return tracked
end

local function saveTracked(folder)
  local lines, oldest = {}, unixNow() - TRACK_DAYS * 86400
  for id, t in pairs(tracked) do
    if t.at >= oldest then
      lines[#lines + 1] = string.format('%d\t%d\t%.0f\t%s', id, t.rating, t.at, t.path)
    else
      tracked[id] = nil
    end
  end
  table.sort(lines)
  writeFile(LrPathUtils.child(folder, Ops.TRACKED), table.concat(lines, '\n') .. (#lines > 0 and '\n' or ''))
end

-- Called after stars and keywords were applied: the stars each photo now has are the starting point.
function Ops.track(folder, plan)
  if LrFileUtils.exists(folder) ~= 'directory' or #plan.items == 0 then return end
  local set, now = trackedSet(folder), unixNow()
  for _, item in ipairs(plan.items) do
    local id = item.photo.photo.localIdentifier
    if id then
      set[id] = { rating = item.setRating or tonumber(item.photo.rating) or 0, at = now, path = item.entry.path }
    end
  end
  saveTracked(folder)
end

--[[ Report star changes made in Lightroom since the last look: one line per change in
lightroom-changes.tsv (time, stars before, stars now, PhotoSelect path). Photos removed from the
catalog are forgotten. Returns the number of changes. ]]
function Ops.syncBack()
  local folder = Ops.selectionsFolder()
  if LrFileUtils.exists(folder) ~= 'directory' then return 0 end
  local set = trackedSet(folder)
  if next(set) == nil then return 0 end
  local catalog = LrApplication.activeCatalog()
  local photos, ids, gone = {}, {}, false
  for id in pairs(set) do
    local photo = catalog:getPhotoByLocalId(id)
    if photo then
      photos[#photos + 1] = photo
      ids[photo] = id
    else
      set[id], gone = nil, true
    end
  end
  local changes, now = {}, unixNow()
  if #photos > 0 then
    local raw = catalog:batchGetRawMetadata(photos, { 'rating' })
    for _, photo in ipairs(photos) do
      local id = ids[photo]
      local rating = tonumber((raw[photo] or {}).rating) or 0
      if rating ~= set[id].rating then
        changes[#changes + 1] = string.format('%.0f\t%d\t%d\t%s', now, set[id].rating, rating, set[id].path)
        set[id].rating = rating
      end
    end
  end
  if #changes > 0 then
    writeFile(LrPathUtils.child(folder, Ops.CHANGES), table.concat(changes, '\n') .. '\n', 'a')
  end
  if #changes > 0 or gone then saveTracked(folder) end
  return #changes
end

-- Test hook: forget what was loaded from applied.txt (as after a Lightroom restart).
function Ops.reset()
  applied, started, tracked, collectionsMade = nil, nil, nil, false
end

return Ops
