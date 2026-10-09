--[[ Lightroom operations shared by the menu command (ApplySelections.lua) and the background task
that applies stars to photos imported from PhotoSelect (Init.lua). The decisions themselves
(parsing, matching, planning) are in SelectionsCore.lua. ]]
local LrApplication = import 'LrApplication'
local LrDate = import 'LrDate'
local LrDialogs = import 'LrDialogs'
local LrFileUtils = import 'LrFileUtils'
local LrPathUtils = import 'LrPathUtils'

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
      if item.setRating then
        photo:setRawMetadata('rating', item.setRating)
      end
    end
  end, { timeout = 60 })
end

local function unixNow()
  return LrDate.currentTime() + 978307200   -- Lightroom counts seconds from 2001-01-01 UTC
end
Ops.unixNow = unixNow

Ops.VERSION = '1.5.0'
Ops.STATUS = 'plugin-status.txt'          -- read by PhotoSelect: is the plug-in running, and what did it do
Ops.APPLIED = 'applied.txt'               -- photos already rated automatically (never twice)
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

-- Test hook: forget what was loaded from applied.txt (as after a Lightroom restart).
function Ops.reset()
  applied, started = nil, nil
end

return Ops
