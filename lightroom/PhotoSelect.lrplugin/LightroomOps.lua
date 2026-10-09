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

--[[ One pass of the background task: if PhotoSelect handed photos to Lightroom's Import window
("Open in Lightroom"), find the ones that have been imported since and apply their stars and
keywords. Stars already set in Lightroom are kept. The request expires after a few hours. ]]
local done = {}
function Ops.applyPending(searchByName)
  local path = LrPathUtils.child(Ops.selectionsFolder(), Ops.PENDING)
  if LrFileUtils.exists(path) ~= 'file' then
    return 0
  end
  local pending = Core.parse(LrFileUtils.readFile(path))
  if not pending or pending.exported + PENDING_HOURS * 3600 < unixNow() then
    LrFileUtils.delete(path)
    return 0
  end
  local catalog = LrApplication.activeCatalog()
  local idx = Core.index({ pending })
  local candidates, remaining = {}, 0
  for _, e in ipairs(pending.entries) do
    local key = string.lower(e.path)
    if not done[key] then
      remaining = remaining + 1
      local photo = catalog:findPhotoByPath(e.path)
      if photo then
        candidates[#candidates + 1] = photo
      elseif searchByName then
        -- imported with Copy: same name, new location (the match below also checks the capture time)
        local ok, found = pcall(function()
          return catalog:findPhotos { searchDesc = { criteria = 'filename', operation = '==', value = e.name } }
        end)
        for _, p in ipairs(ok and found or {}) do
          candidates[#candidates + 1] = p
        end
      end
    end
  end
  if #candidates == 0 then
    return 0
  end
  local plan = Core.plan(idx, Ops.describePhotos(catalog, candidates), false)
  local fresh = { items = {}, rated = 0 }
  for _, item in ipairs(plan.items) do
    local key = string.lower(item.entry.path)
    if not done[key] then
      done[key] = true
      fresh.items[#fresh.items + 1] = item
      if item.setRating then fresh.rated = fresh.rated + 1 end
    end
  end
  if #fresh.items == 0 then
    return 0
  end
  Ops.apply(catalog, fresh)
  local left = 0
  for _, e in ipairs(pending.entries) do
    if not done[string.lower(e.path)] then left = left + 1 end
  end
  if left == 0 then
    LrFileUtils.delete(path)
    done = {}
  end
  if LrDialogs.showBezel then
    LrDialogs.showBezel(string.format('PhotoSelect: stars applied to %d imported photos', #fresh.items), 4)
  end
  return #fresh.items
end

return Ops
