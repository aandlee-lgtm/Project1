--[[ Runs when Lightroom Classic starts (LrForceInitPlugin): a light background task that applies
PhotoSelect's stars to photos imported through "Open in Lightroom", once they appear in the catalog.
It only does work while PhotoSelect has handed photos to Lightroom (a pending.import file exists). ]]
local LrTasks = import 'LrTasks'
local Ops = require 'LightroomOps'

LrTasks.startAsyncTask(function()
  local round = 0
  while not Ops.stopped do
    round = round + 1
    LrTasks.pcall(Ops.applyPending, round % 4 == 0)   -- the slower name search every fourth pass
    LrTasks.sleep(4)
  end
end)
