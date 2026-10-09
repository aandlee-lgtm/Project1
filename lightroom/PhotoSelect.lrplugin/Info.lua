--[[ PhotoSelect plug-in for Adobe Lightroom Classic.
Applies the selections saved by PhotoSelect ("Send to Lightroom") to the photos selected, or shown,
in the Library: star ratings (Keep 3, Consider 2, Drop 1, Liked 5) and keywords under "PhotoSelect".
Photos PhotoSelect hands to Lightroom's Import window ("Open in Lightroom") get them automatically
once imported (Init.lua).
Installed by PhotoSelect: Help > Install Lightroom Plug-in... ]]
return {
  LrSdkVersion = 6.0,
  LrSdkMinimumVersion = 6.0,
  LrToolkitIdentifier = 'app.photoselect.lightroom',
  LrPluginName = 'PhotoSelect',
  LrPluginInfoUrl = 'https://github.com/aandlee-lgtm/Project1',
  LrInitPlugin = 'Init.lua',
  LrForceInitPlugin = true,
  LrShutdownPlugin = 'Shutdown.lua',
  LrLibraryMenuItems = {
    { title = 'Apply PhotoSelect Selections...', file = 'ApplySelections.lua' },
  },
  VERSION = { major = 1, minor = 4, revision = 0 },
}
