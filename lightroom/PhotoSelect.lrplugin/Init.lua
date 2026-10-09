--[[ Runs when Lightroom Classic starts (LrForceInitPlugin): a light background task that applies
PhotoSelect's stars and keywords to photos once they are in the catalog, with no command to run, and
reports that the plug-in is running (plugin-status.txt, shown in PhotoSelect's Lightroom window).
It does real work only while selections are waiting to be applied. ]]
local LrTasks = import 'LrTasks'
local Ops = require 'LightroomOps'

LrTasks.startAsyncTask(function()
  local round = 0
  while not Ops.stopped do
    round = round + 1
    LrTasks.pcall(Ops.autoApply, round, 8)              -- capture-date lookups every 8th pass (~30 s)
    if round % 8 == 1 then
      LrTasks.pcall(Ops.writeStatus, Ops.selectionsFolder())
    end
    LrTasks.sleep(4)
  end
end)
