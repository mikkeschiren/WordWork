-- Word Work: rensar importerade dokument till sådant som Markdown och
-- editorn kan uttrycka. Ingen text ska försvinna – bara formatering.
--
--  * understrykning, kapitäler, upphöjt/nedsänkt, spans och divs packas upp
--  * bilder och rå HTML/XML tas bort (editorn hanterar bara text)
--  * tabeller blir ett stycke per rad med cellerna åtskilda av " – "
--  * fotnoter blir upphöjda siffror (¹ ² …) med en lista "Fotnoter" sist

local notes = {}

local function unwrap(el) return el.content end

Underline = unwrap
SmallCaps = unwrap
Superscript = unwrap
Subscript = unwrap
Span = unwrap
Div = unwrap

function Image(el)
  return {}
end

function Figure(el)
  return {}
end

function RawInline(el) return {} end
function RawBlock(el) return {} end

local SUP = { ["0"]="⁰", ["1"]="¹", ["2"]="²", ["3"]="³", ["4"]="⁴",
              ["5"]="⁵", ["6"]="⁶", ["7"]="⁷", ["8"]="⁸", ["9"]="⁹" }

local function superscript(n)
  return (tostring(n):gsub("%d", SUP))
end

function Note(el)
  table.insert(notes, el.content)
  return pandoc.Str(superscript(#notes))
end

local function cells_to_para(row)
  local parts = {}
  for _, cell in ipairs(row.cells) do
    local text = pandoc.utils.stringify(cell.contents)
    if text ~= "" then table.insert(parts, text) end
  end
  if #parts == 0 then return nil end
  return pandoc.Para({ pandoc.Str(table.concat(parts, " – ")) })
end

function Table(tbl)
  local out = {}
  local function add_rows(rows)
    for _, row in ipairs(rows) do
      local p = cells_to_para(row)
      if p then table.insert(out, p) end
    end
  end
  add_rows(tbl.head.rows)
  for _, body in ipairs(tbl.bodies) do
    add_rows(body.head)
    add_rows(body.body)
  end
  add_rows(tbl.foot.rows)
  return out
end

function Pandoc(doc)
  -- Filtren ovan har redan körts på blocken när Pandoc-funktionen anropas
  -- (den körs sist i samma pass), så fotnoterna är insamlade här.
  if #notes > 0 then
    doc.blocks:insert(pandoc.Header(2, { pandoc.Str("Fotnoter") }))
    local items = {}
    for _, content in ipairs(notes) do
      table.insert(items, content)
    end
    doc.blocks:insert(pandoc.OrderedList(items))
  end
  -- Metadata som enkel text, så frontmatter blir läsbar.
  for key, value in pairs(doc.meta) do
    if type(value) == "table" and value.t ~= "MetaList" and value.t ~= "MetaMap" then
      doc.meta[key] = pandoc.MetaString(pandoc.utils.stringify(value))
    end
  end
  return doc
end
