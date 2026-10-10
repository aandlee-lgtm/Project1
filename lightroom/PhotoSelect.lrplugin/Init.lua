--[[ Runs when Lightroom Classic starts (LrForceInitPlugin): a light background task that applies
PhotoSelect's stars and keywords to photos once they are in the catalog, with no command to run, and
reports that the plug-in is running (plugin-status.txt, shown in PhotoSelect's Lightroom window), and
reports star changes made in Lightroom back to PhotoSelect (lightroom-changes.tsv).
It does real work only while selections are waiting to be applied. ]]
local LrTasks = import 'LrTasks'
local Ops = require 'LightroomOps'

LrTasks.startAsyncTask(function()
  local round = 0
  while not Ops.stopped do
    round = round + 1
    local ok, err = LrTasks.pcall(Ops.autoApply, round, 8)   -- catalog searches every 8th pass (~30 s)
    if not ok then Ops.noteError('automatic rating: ' .. tostring(err)) end
    if round % 4 == 0 then
      ok, err = LrTasks.pcall(Ops.syncBack)               -- star changes made in Lightroom, every ~16 s
      if not ok then Ops.noteError('reading star changes: ' .. tostring(err)) end
    end
    if round % 8 == 1 then
      LrTasks.pcall(Ops.writeStatus, Ops.selectionsFolder())
    end
    LrTasks.sleep(4)
  end
end)
