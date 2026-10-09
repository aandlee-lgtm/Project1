--[[ PhotoSelect plug-in for Adobe Lightroom Classic.
Applies the selections saved by PhotoSelect ("Send to Lightroom") to the photos selected, or shown,
in the Library: star ratings (Keep 3, Consider 2, Drop 1, Liked 5) and keywords under "PhotoSelect".
Photos get them automatically once they are in the catalog, however they were imported (Init.lua).
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
  VERSION = { major = 1, minor = 5, revision = 0 },
}
