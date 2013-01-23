dofile("urlcode.lua")
dofile("table_show.lua")
JSON = (loadfile "JSON.lua")()

local url_count = 0

load_json_file = function(file)
  if file then
    local f = io.open(file)
    local data = f:read("*all")
    f:close()
    return JSON:decode(data)
  else
    return nil
  end
end

read_file = function(file)
  if file then
    local f = io.open(file)
    local data = f:read("*all")
    f:close()
    return data
  else
    return ""
  end
end

wget.callbacks.get_urls = function(file, url, is_css, iri)
  -- progress message
  url_count = url_count + 1
  if url_count % 20 == 0 then
    io.stdout:write("\r - Downloaded "..url_count.." URLs")
    io.stdout:flush()
  end

  local urls = {}
  local html = nil

  -- audio - download the necessary files, it will probably work in the WARC
  if string.match(url, "%.xanga%.com/audio/audioplayerinfo%.aspx") then
    local xml = read_file(file)
    for audio_url in string.gmatch(xml, "(http://[^<]+%.mp3)") do
      table.insert(urls, { url=audio_url })
    end

  elseif string.match(url, "%.xanga%.com/audio/[^/]+/$") then
    if not html then
      html = read_file(file)
    end

    local player_url = string.match(html, "http://www%.xanga%.com/media/xangaaudioplayer%.swf%?[^\"]+")
    if player_url then
      table.insert(urls, { url=player_url })
      table.insert(urls, { url="http://www.xanga.com/media/audioplayer/itemconfig.xml" })

      local audio_id = string.match(player_url, "i=[0-9a-zA-Z]+&m=[0-9a-zA-Z]+")
      if audio_id then
        table.insert(urls, { url=("http://www.xanga.com/audio/audioplayerinfo.aspx?"..audio_id) })
        table.insert(urls, { url=("http://www.xanga.com/audio/audioplayerinfoplayed.aspx?"..audio_id) })
      end
    end
  end

  -- video - download the files
  -- the video still won't work in the WARC, because:
  --   1. the script adds "random=" + Math.random() to the swf url)
  --   2. we don't download the ads from videoegg.com
  if string.match(url, "%.xanga%.com/videos/[^/]+/$") then
    if not html then
      html = read_file(file)
    end

    local player_url = string.match(html, "http://www%.xanga%.com/media/xangavideoplayer%.swf%?[^\"]+")
    if player_url then
      table.insert(urls, { url=player_url })
      table.insert(urls, { url="http://www.xanga.com/videos/Services/XangaVideoPlayer.asmx?WSDL" })

      local video_id = string.match(player_url, "i=([^&]+)&")
      local video_md5 = string.match(player_url, "m=([^&]+)&")
      if video_id and video_md5 then
        -- the actual script POSTs an XML document, but this works too
        table.insert(urls, { url="http://www.xanga.com/videos/Services/XangaVideoPlayer.asmx/GetVideo",
                             post_data=("videoId="..video_id.."&md5="..video_md5)})
      end
    end
  end

  -- photos, load for filmstrip
  if string.match(url, "%.xanga%.com/photos/[^/]+/$") then
    if not html then
      html = read_file(file)
    end
  end

  -- filmstrip
  if html and string.match(html, "values = new FilmStripValues") then
    local user_id = string.match(html, "values.UserId = ([0-9]+);")
    local username = string.match(html, "values.Username = \"([^\"]+)\";")
    local page_type = string.match(html, "values.PageType = \"([^\"]+)\";")
    local item_id = string.match(html, "values.ItemId = ([0-9]+);")
    local album = string.match(html, "values.Album = \"([^\"]+)\";")
    local row_number = string.match(html, "values.RowNumber = ([0-9]+);")

    if user_id then
      -- http://s.xanga.com/media/scripts/filmstrip6.js
      local fields = {}
      fields["userId"] = user_id
      fields["username"] = username
      fields["album"] = album
      if album == "0" then
        fields["anchor"] = item_id
      else
        fields["anchor"] = row_number
      end

      local method = nil
      if page_type == "Album" then
        method = "GetAdjacentAlbumCenter"
      elseif page_type == "Photoblog" then
        method = "GetAdjacentPhotosCenter"
      elseif page_type == "Videoblog" then
        method = "GetAdjacentVideosCenter"
      end

      if method then
        -- the actual script POSTs a JSON document, but this works too
        table.insert(urls, { url=("http://"..username..".xanga.com/photos/Services/FilmStrip.asmx/"..method),
                             post_data=cgilua.urlcode.encodetable(fields) })
      end
    end
  end

  -- extract urls from videoplayer, filmstrip
  if string.match(url, "http://www%.xanga%.com/videos/Services/XangaVideoPlayer%.asmx/GetVideo")
     or string.match(url, "%.xanga%.com/photos/Services/FilmStrip%.asmx") then
    local xml = read_file(file)
    for url in string.gmatch(xml, "<FlvUrl>(http://[^<\"]+)") do
      table.insert(urls, { url=url })
    end
    for url in string.gmatch(xml, "<ImageUrl>(http://[^<\"]+)") do
      table.insert(urls, { url=url })
    end
    for url in string.gmatch(xml, "<Image[0-9]+>(http://[^<\"]+)") do
      table.insert(urls, { url=url })
    end
    for url in string.gmatch(xml, "<NavigatingUrl>(http://[^<\"]+)") do
      table.insert(urls, { url=url, link_expect_html=1 })
    end
  end

  -- image scaling
  local img_base, img_id = string.match(url, "^(http://x.+%.xanga%.com/[a-z0-9]+/)[qtszmbo]([a-z0-9]+%.jpg)$")
  if img_base and img_id then
    table.insert(urls, { url=(img_base.."q"..img_id) })
    table.insert(urls, { url=(img_base.."t"..img_id) })
    table.insert(urls, { url=(img_base.."s"..img_id) })
    table.insert(urls, { url=(img_base.."z"..img_id) })
    table.insert(urls, { url=(img_base.."m"..img_id) })
    table.insert(urls, { url=(img_base.."b"..img_id) })
    table.insert(urls, { url=(img_base.."o"..img_id) })
  end
  local img_base, img_id = string.match(url, "^(http://p.+%.xanga%.com/[a-z0-9]+/[a-z0-9]+/)t/([a-z0-9]+%.jpg)$")
  if img_base and img_id then
    table.insert(urls, { url=(img_base..img_id) })
  end

  return urls
end

wget.callbacks.download_child_p = function(urlpos, parent, depth, start_url_parsed, iri, verdict, reason)
  -- print(table.show({urlpos=urlpos, parent=parent, start_url_parsed=start_url_parsed, verdict=verdict, reason=reason}))

  -- get inline links from other hosts
  if start_url_parsed["host"] == urlpos["url"]["host"] then
    -- follow normal decision
    local url = urlpos["url"]["url"]
    if string.match(url, "%.xanga%.com/Amazon/") then
      -- don't fall into the Amazon redirect trap
      return false
    end
    return verdict
  else
    if not verdict and reason == "DIFFERENT_HOST" then
      if urlpos["link_inline_p"] == 1 then
        -- get inline links from other hosts
        return true
      elseif urlpos["link_expect_html"] == 0 and urlpos["link_expect_css"] == 0 then
        -- inline links but not marked as such
        return true
      end

      local username = string.match(start_url_parsed["host"], "^([^.]+)%.xanga%.com")
      local url = urlpos["url"]["url"]
      -- a few other urls we want to get
      if string.match(url, "^http://photo%.xanga%.com/"..username.."/")
         or string.match(url, "^http://www%.xanga%.com/"..username.."$")
         or string.match(url, "^http://www%.xanga%.com/"..username.."/")
         or string.match(url, "^http://weblog%.xanga%.com/"..username.."/")
         or string.match(url, "^http://x[a-z0-9][a-z0-9]%.xanga%.com/.+%.jpg$") then
        return true
      end
    end

    -- do not further recurse on other hosts
    return false
  end
end

