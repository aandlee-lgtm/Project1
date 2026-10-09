--[[ Library > Plug-in Extras > Apply PhotoSelect Selections...
Applies PhotoSelect's selections to the selected photos, or to all photos shown in the Library when
at most one is selected: star ratings and keywords under "PhotoSelect". Shows a summary first and
changes nothing unless you click Apply. Star ratings already set in Lightroom are kept unless you
tick the box to replace them. ]]
local LrApplication = import 'LrApplication'
local LrBinding = import 'LrBinding'
local LrDialogs = import 'LrDialogs'
local LrFunctionContext = import 'LrFunctionContext'
local LrTasks = import 'LrTasks'
local LrView = import 'LrView'

local Core = require 'SelectionsCore'
local Ops = require 'LightroomOps'
local TITLE = Ops.TITLE

local function run(context)
  local catalog = LrApplication.activeCatalog()
  -- several selected photos, or else every photo in the current folder / collection / import
  local photos = catalog:getMultipleSelectedOrAllPhotos()
  if #photos == 0 then
    LrDialogs.message(TITLE, 'There are no photos in the current view. Import the folder you analysed in PhotoSelect, '
      .. 'or select it in the Library, then try again.', 'info')
    return
  end
  -- with one photo selected Lightroom gives the whole view; say so, since that is not what was selected
  local scope = #catalog:getTargetPhotos() < #photos and string.format('all %d photos shown', #photos)
    or string.format('%d photos', #photos)
  local folder = Ops.selectionsFolder()
  local files = Ops.loadSelections(folder)
  if #files == 0 then
    LrDialogs.message(TITLE, 'No PhotoSelect selections were found. In PhotoSelect, analyse the folder and click "Send to Lightroom", then try again.\n\nLooked in: ' .. folder, 'info')
    return
  end
  local idx = Core.index(files)
  local described = Ops.describePhotos(catalog, photos)
  local plan = Core.plan(idx, described, false)
  if plan.matched == 0 then
    LrDialogs.message(TITLE, Core.summary(plan, #photos, idx.count, scope, idx) .. '\n\nNothing to apply.', 'info')
    return
  end

  local props = LrBinding.makePropertyTable(context)
  props.overwrite = false
  local f = LrView.osFactory()
  local contents = f:column {
    bind_to_object = props,
    spacing = f:control_spacing(),
    f:static_text { title = Core.summary(plan, #photos, idx.count, scope, idx), width_in_chars = 70, height_in_lines = 9 },
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
  Ops.apply(catalog, plan)
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
