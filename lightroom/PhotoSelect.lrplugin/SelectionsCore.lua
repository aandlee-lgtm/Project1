--[[ Pure-Lua logic of the PhotoSelect plug-in (no Lightroom SDK calls), so it can be tested outside
Lightroom: reading PhotoSelect's selections files, matching Lightroom photos to them, and planning
the changes. ApplySelections.lua does the Lightroom part. ]]
local Core = {}

local function split(text, sep)
  local out, start = {}, 1
  while true do
    local i = string.find(text, sep, start, true)
    if not i then
      out[#out + 1] = string.sub(text, start)
      return out
    end
    out[#out + 1] = string.sub(text, start, i - 1)
    start = i + #sep
  end
end
Core.split = split

local function basename(path)
  return (string.match(path or '', '([^/\\]+)$') or path or '')
end

local function extension(name)
  return string.lower(string.match(name or '', '%.([^%.]+)$') or '')
end

local function stem(name)
  return string.lower(string.match(name or '', '^(.*)%.[^%.]+$') or name or '')
end

-- 'YYYY-MM-DD HH:MM:SS' to seconds (calendar arithmetic only, no time zone), or nil.
local function seconds(text)
  local y, mo, d, h, mi, s = string.match(text or '', '^(%d+)-(%d+)-(%d+) (%d+):(%d+):(%d+)')
  if not y then return nil end
  y, mo = tonumber(y), tonumber(mo)
  if mo <= 2 then y, mo = y - 1, mo + 12 end
  local days = 365 * y + math.floor(y / 4) - math.floor(y / 100) + math.floor(y / 400)
    + math.floor((153 * (mo - 3) + 2) / 5) + tonumber(d)
  return ((days * 24 + tonumber(h)) * 60 + tonumber(mi)) * 60 + tonumber(s)
end
Core.seconds = seconds

-- Parse one selections file. Returns { exported = seconds, folder = text, entries = { ... } } or nil, error.
function Core.parse(text)
  text = string.gsub(text or '', '\r\n', '\n')
  local lines = split(text, '\n')
  local head = split(lines[1] or '', '\t')
  if head[1] ~= '# PhotoSelect selections' or head[2] ~= '1' then
    return nil, 'not a PhotoSelect selections file (or made by a newer PhotoSelect)'
  end
  local fields = split(lines[2] or '', '\t')
  local index = {}
  for i, f in ipairs(fields) do index[f] = i end
  for _, f in ipairs({ 'path', 'name', 'capture', 'rating', 'keywords' }) do
    if not index[f] then return nil, 'missing column ' .. f end
  end
  local result = { exported = tonumber(head[3]) or 0, folder = head[4] or '', entries = {} }
  for n = 3, #lines do
    if lines[n] ~= '' then
      local v = split(lines[n], '\t')
      local rating = tonumber(v[index.rating])
      if rating and rating >= 0 and rating <= 5 then
        local keywords = {}
        for _, k in ipairs(split(v[index.keywords] or '', '|')) do
          if k ~= '' then keywords[#keywords + 1] = k end
        end
        result.entries[#result.entries + 1] = {
          path = v[index.path] or '', name = basename(v[index.name]), capture = v[index.capture] or '',
          rating = rating, keywords = keywords,
          decision = index.decision and v[index.decision] or '',
        }
      end
    end
  end
  return result
end

-- Build lookup tables from parsed files; entries from later exports replace earlier ones.
function Core.index(files)
  table.sort(files, function(a, b) return a.exported < b.exported end)
  local idx = { byPath = {}, byNameTime = {}, byTime = {}, byName = {}, byStem = {}, byStemTime = {}, names = {}, count = 0 }
  for _, f in ipairs(files) do
    for _, e in ipairs(f.entries) do
      local old = idx.byPath[string.lower(e.path)]
      if old then old.replaced = true end
      idx.byPath[string.lower(e.path)] = e
      local named = idx.byName[string.lower(e.name)] or {}
      named[#named + 1] = e
      idx.byName[string.lower(e.name)] = named
      local stemmed = idx.byStem[stem(e.name)] or {}
      stemmed[#stemmed + 1] = e
      idx.byStem[stem(e.name)] = stemmed
      idx.names[#idx.names + 1] = e.name
      if e.capture ~= '' then
        idx.byNameTime[string.lower(e.name) .. '|' .. e.capture] = e
        idx.byStemTime[stem(e.name) .. '|' .. e.capture] = e
        local list = idx.byTime[e.capture] or {}
        list[#list + 1] = e
        idx.byTime[e.capture] = list
      end
      idx.count = idx.count + 1
    end
  end
  return idx
end

--[[ Find the PhotoSelect entry for a Lightroom photo described by
{ path =, fileName =, preservedFileName =, capture = 'YYYY-MM-DD HH:MM:SS' }:
1. the same file (imported with Add, or PhotoSelect analysed the imported copy);
2. the same file name (current or original, before renaming) and capture time to the second
   (imported with Copy or Move);
3. the same name without its extension and the same capture time (imported with Copy as DNG);
4. the same file name, or name without extension, when only one PhotoSelect photo has it;
5. the same name and a capture time differing by whole hours only (camera or Lightroom time zone);
6. otherwise the only analysed photo with that capture time and file type (renamed on import).
Returns entry, how. ]]
function Core.match(idx, photo)
  local e = idx.byPath[string.lower(photo.path or '')]
  if e then return e, 'path' end
  local capture = photo.capture or ''
  local names = {}
  for _, name in ipairs({ photo.fileName, photo.preservedFileName }) do
    if name and name ~= '' then names[#names + 1] = string.lower(basename(name)) end
  end
  if capture ~= '' then
    for _, name in ipairs(names) do
      e = idx.byNameTime[name .. '|' .. capture]
      if e then return e, 'name' end
    end
    for _, name in ipairs(names) do
      e = idx.byStemTime[stem(name) .. '|' .. capture]
      if e then return e, 'name' end
    end
  end
  local function only(list, accept)
    local found = nil
    for _, c in ipairs(list or {}) do
      if not c.replaced and (not accept or accept(c)) then
        if found then return nil end
        found = c
      end
    end
    return found
  end
  for _, name in ipairs(names) do
    local found = only(idx.byName[name]) or only(idx.byStem[stem(name)])
    if found then return found, 'name' end
  end
  local t = seconds(capture)
  if t then
    local function hoursApart(c)
      local u = seconds(c.capture)
      local d = u and math.abs(u - t)
      return d and d > 0 and d <= 14 * 3600 and d % 3600 == 0
    end
    for _, name in ipairs(names) do
      local found = only(idx.byStem[stem(name)], hoursApart)
      if found then return found, 'time zone' end
    end
  end
  if capture == '' then return nil end
  if capture == '' then return nil end
  local list = idx.byTime[capture]
  if list then
    local found
    for _, c in ipairs(list) do
      if not c.replaced and extension(c.name) == extension(photo.fileName) then
        if found then return nil, 'ambiguous' end
        found = c
      end
    end
    if found then return found, 'time' end
  end
  return nil
end

--[[ Plan the changes for a list of photos { path, fileName, preservedFileName, capture, rating }.
Returns a plan with one item per matched photo { photo, entry, setRating } and counts:
matched, notFound, ambiguous, conflicts (a different star rating is already set in Lightroom),
unchanged (rating already right). With overwrite false, conflicting ratings are left as they are
(keywords are still applied). ]]
function Core.plan(idx, photos, overwrite)
  local plan = { items = {}, matched = 0, notFound = 0, ambiguous = 0, conflicts = 0, unchanged = 0, rated = 0, unmatched = {} }
  for _, p in ipairs(photos) do
    local e, how = Core.match(idx, p)
    if e then
      plan.matched = plan.matched + 1
      local current = tonumber(p.rating) or 0
      local setRating = nil
      if current == e.rating then
        plan.unchanged = plan.unchanged + 1
      elseif current > 0 then
        plan.conflicts = plan.conflicts + 1
        if overwrite then setRating = e.rating end
      else
        setRating = e.rating
      end
      if setRating then plan.rated = plan.rated + 1 end
      plan.items[#plan.items + 1] = { photo = p, entry = e, setRating = setRating, how = how }
    elseif how == 'ambiguous' then
      plan.ambiguous = plan.ambiguous + 1
      plan.unmatched[#plan.unmatched + 1] = basename(p.fileName or p.path)
    else
      plan.notFound = plan.notFound + 1
      plan.unmatched[#plan.unmatched + 1] = basename(p.fileName or p.path)
    end
  end
  return plan
end

-- Plain-language summary shown before anything is changed. scope describes which photos were
-- checked, e.g. 'the 3 selected photos' or 'all 120 photos shown in the Library'.
function Core.summary(plan, total, selectionCount, scope, idx)
  local lines = {
    string.format('Checked %s: %d of %d match PhotoSelect selections (%d photos available).',
      scope or (total .. ' photos'), plan.matched, total, selectionCount),
  }
  if plan.notFound > 0 then
    lines[#lines + 1] = string.format('%d photos were not found in PhotoSelect and will be left as they are.', plan.notFound)
  end
  if plan.ambiguous > 0 then
    lines[#lines + 1] = string.format('%d photos could not be matched with certainty (renamed, same capture second) and will be left as they are.', plan.ambiguous)
  end
  if plan.unchanged > 0 then
    lines[#lines + 1] = string.format('%d already have the right star rating.', plan.unchanged)
  end
  if plan.conflicts > 0 then
    lines[#lines + 1] = string.format('%d already have a different star rating set in Lightroom.', plan.conflicts)
  end
  if #plan.unmatched > 0 then
    local shown = {}
    for i = 1, math.min(10, #plan.unmatched) do shown[i] = plan.unmatched[i] end
    lines[#lines + 1] = 'Not matched: ' .. table.concat(shown, ', ') .. (#plan.unmatched > 10 and ', …' or '')
    if idx and #idx.names > 0 then
      local names = {}
      for i, n in ipairs(idx.names) do names[i] = n end
      table.sort(names)
      lines[#lines + 1] = string.format('PhotoSelect has %d photos named %s … %s. If these are not the photos you imported, '
        .. 'import that folder first.', #names, names[1], names[#names])
    end
  end
  lines[#lines + 1] = 'Stars: Keep 3, Consider 2, Drop 1, Liked 5. Keywords are added under "PhotoSelect".'
  return table.concat(lines, '\n')
end

Core.basename = basename
return Core
