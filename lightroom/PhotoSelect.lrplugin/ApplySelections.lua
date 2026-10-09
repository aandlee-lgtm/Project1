--[[ Library > Plug-in Extras > Apply PhotoSelect Selections...
Applies PhotoSelect's selections to the photos selected in the Library (all photos shown in the
filmstrip when none are selected): star ratings and keywords under "PhotoSelect". Shows a summary
first and changes nothing unless you click Apply. Star ratings already set in Lightroom are kept
unless you tick the box to replace them. ]]
local LrApplication = import 'LrApplication'
local LrBinding = import 'LrBinding'
local LrDate = import 'LrDate'
local LrDialogs = import 'LrDialogs'
local LrFileUtils = import 'LrFileUtils'
local LrFunctionContext = import 'LrFunctionContext'
local LrPathUtils = import 'LrPathUtils'
local LrTasks = import 'LrTasks'
local LrView = import 'LrView'

local Core = require 'SelectionsCore'
local TITLE = 'Apply PhotoSelect Selections'

local function selectionsFolder()
  local ok, config = pcall(require, 'Config')
  if ok and type(config) == 'table' and config.selectionsFolder then
    return config.selectionsFolder
  end
  return LrPathUtils.child(LrPathUtils.getStandardFilePath('home'), 'Library/Application Support/PhotoSelect/Lightroom')
end

local function loadSelections(folder)
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

local function describePhotos(catalog, photos)
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

local function apply(catalog, plan)
  catalog:withWriteAccessDo(TITLE, function()
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

local function run(context)
  local catalog = LrApplication.activeCatalog()
  local photos = catalog:getTargetPhotos()
  if #photos == 0 then
    LrDialogs.message(TITLE, 'There are no photos in the current view. Select the imported folder in the Library first.', 'info')
    return
  end
  local folder = selectionsFolder()
  local files = loadSelections(folder)
  if #files == 0 then
    LrDialogs.message(TITLE, 'No PhotoSelect selections were found. In PhotoSelect, analyse the folder and click "Send to Lightroom", then try again.\n\nLooked in: ' .. folder, 'info')
    return
  end
  local idx = Core.index(files)
  local described = describePhotos(catalog, photos)
  local plan = Core.plan(idx, described, false)
  if plan.matched == 0 then
    LrDialogs.message(TITLE, Core.summary(plan, #photos, idx.count) .. '\n\nNothing to apply. Check that these are the photos you analysed in PhotoSelect.', 'info')
    return
  end

  local props = LrBinding.makePropertyTable(context)
  props.overwrite = false
  local f = LrView.osFactory()
  local contents = f:column {
    bind_to_object = props,
    spacing = f:control_spacing(),
    f:static_text { title = Core.summary(plan, #photos, idx.count), width_in_chars = 70, height_in_lines = 7 },
    f:checkbox {
      title = string.format('Replace star ratings already set in Lightroom (%d photos)', plan.conflicts),
      value = LrView.bind('overwrite'),
      enabled = plan.conflicts > 0,
    },
  }
  local result = LrDialogs.presentModalDialog { title = TITLE, contents = contents, actionVerb = 'Apply' }
  if result ~= 'ok' then
    return
  end
  if props.overwrite then
    plan = Core.plan(idx, described, true)
  end
  apply(catalog, plan)
  LrDialogs.message(TITLE, string.format('Applied to %d photos: %d star ratings set, keywords under "PhotoSelect" updated.',
    plan.matched, plan.rated), 'info')
end

LrTasks.startAsyncTask(function()
  LrFunctionContext.callWithContext('PhotoSelect', function(context)
    context:addFailureHandler(function(_, message)
      LrDialogs.message(TITLE, 'Something went wrong: ' .. tostring(message), 'critical')
    end)
    run(context)
  end)
end)
