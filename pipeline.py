import os
import os.path
import shutil
import time
from distutils.version import StrictVersion

import functools
from tornado.httpclient import AsyncHTTPClient, HTTPRequest

import seesaw
if StrictVersion(seesaw.__version__) < StrictVersion("0.0.15"):
  raise Exception("This pipeline needs seesaw version 0.0.15 or higher.")

from seesaw.project import *
from seesaw.config import *
from seesaw.item import *
from seesaw.task import *
from seesaw.pipeline import *
from seesaw.externalprocess import *
from seesaw.tracker import *
from seesaw.util import find_executable


WGET_LUA = find_executable("Wget+Lua",
    [ "GNU Wget 1.14.lua.20130120-8476",
      "GNU Wget 1.14.lua.20130407-1f1d",
      "GNU Wget 1.14.lua.20130427-92d2",
      "GNU Wget 1.14.lua.20130523-9a5c" ],
    [ "./wget-lua",
      "./wget-lua-warrior",
      "./wget-lua-local",
      "../wget-lua",
      "../../wget-lua",
      "/home/warrior/wget-lua",
      "/usr/bin/wget-lua" ])

if not WGET_LUA:
  raise Exception("No usable Wget+Lua found.")


USER_AGENT = "Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US) AppleWebKit/533.20.25 (KHTML, like Gecko) Version/5.0.4 Safari/533.20.27"
VERSION = "20130605.01"


class PrepareDirectories(SimpleTask):
  def __init__(self, warc_prefix):
    SimpleTask.__init__(self, "PrepareDirectories")
    self.warc_prefix = warc_prefix

  def process(self, item):
    item_name = item["item_name"]
    dirname = "/".join(( item["data_dir"], item_name ))

    if os.path.isdir(dirname):
      shutil.rmtree(dirname)
    os.makedirs(dirname)

    item["item_dir"] = dirname
    item["warc_file_base"] = "%s-%s-%s" % (self.warc_prefix, item_name, time.strftime("%Y%m%d-%H%M%S"))

    open("%(item_dir)s/%(warc_file_base)s.warc.gz" % item, "w").close()

class MoveFiles(SimpleTask):
  def __init__(self):
    SimpleTask.__init__(self, "MoveFiles")

  def process(self, item):
    os.rename("%(item_dir)s/%(warc_file_base)s.warc.gz" % item,
              "%(data_dir)s/%(warc_file_base)s.warc.gz" % item)

    shutil.rmtree("%(item_dir)s" % item)


class Login(SimpleTask):
  def __init__(self):
    SimpleTask.__init__(self, "Login")

  def enqueue(self, item):
    self.start_item(item)
    self.login(item)

  def login(self, item):
    http_client = AsyncHTTPClient()
    item.log_output("Logging in on www.xanga.com... ", full_line = False)

    http_client.fetch("http://www.xanga.com/default.aspx",
        functools.partial(self.handle_response, item),
        method="POST",
        body="IsPostBack=true&XangaHeader%24txtSigninUsername=archiveteam&XangaHeader%24txtSigninPassword=archiveteam",
        follow_redirects=False,
        user_agent=USER_AGENT)

  def handle_response(self, item, response):
    if response.code == 302:
      keys = set()
      lines = []
      for cookie_header in response.headers.get_list("Set-Cookie"):
        key, value = cookie_header.split(";")[0].split("=", 1)
        keys.add(key)
        lines.append("\t".join((".xanga.com", "TRUE", "/", "FALSE", "0", key, value)))

      if "u" in keys and "x" in keys and "y" in keys:
        item.log_output("OK.\n", full_line=False)
        item["cookie_jar"] = "%(item_dir)s/cookies.txt" % item
        with open(item["cookie_jar"], "w") as f:
          f.write("\n".join(lines))
          f.write("\n\n\n\n")
        self.complete_item(item)
        return

    item.log_output("failed (response code %d)\n" % response.code, full_line=False)
    self.fail_item(item)





project = Project(
  title = "Xanga",
  project_html = """
    <img class="project-logo" alt="Weblog.nl logo" src="http://archiveteam.org/images/4/4d/Xanga-logo-main.gif" width="120" />
    <h2>Xanga.com <span class="links"><a href="http://www.xanga.com/">Website</a> &middot; <a href="http://tracker.archiveteam.org/xanga/">Leaderboard</a></span></h2>
    <p><i>Xanga</i> is getting old. Archive Team investigates.</p>
  """
  # , utc_deadline = datetime.datetime(2013,03,01, 23,59,0)
)

TRACKER_ID = "xanga"
RSYNC_TARGET = ConfigInterpolation("fos.textfiles.com::alardland/warrior/xanga/%s/", downloader)

pipeline = Pipeline(
  GetItemFromTracker("http://tracker.archiveteam.org/%s" % TRACKER_ID, downloader, VERSION),
  PrepareDirectories(warc_prefix="xanga.com"),
  Login(),
  WgetDownload([ WGET_LUA,
      "-U", USER_AGENT,
      "-nv",
      "-o", ItemInterpolation("%(item_dir)s/wget.log"),
      "--load-cookies", ItemInterpolation("%(cookie_jar)s"),
      "--lua-script", "xanga.lua",
      "--no-check-certificate",
      "--output-document", ItemInterpolation("%(item_dir)s/wget.tmp"),
      "--truncate-output",
      "-e", "robots=off",
      "--rotate-dns",
      "--recursive", "--level=inf",
      "--page-requisites",
      "--timeout", "60",
      "--tries", "20",
      "--waitretry", "5",
      "--warc-file", ItemInterpolation("%(item_dir)s/%(warc_file_base)s"),
      "--warc-header", "operator: Archive Team",
      "--warc-header", "xanga-dld-script-version: " + VERSION,
      "--warc-header", ItemInterpolation("xanga-user: %(item_name)s"),
      ItemInterpolation("http://%(item_name)s.xanga.com/")
    ],
    max_tries = 2,
    accept_on_exit_code = [ 0, 4, 6, 8 ],
  ),
  PrepareStatsForTracker(
    defaults = { "downloader": downloader, "version": VERSION },
    file_groups = {
      "data": [ ItemInterpolation("%(item_dir)s/%(warc_file_base)s.warc.gz") ]
    }
  ),
  MoveFiles(),
  LimitConcurrent(NumberConfigValue(min=1, max=4, default="1", name="shared:rsync_threads", title="Rsync threads", description="The maximum number of concurrent uploads."),
    UploadWithTracker(
      "http://tracker.archiveteam.org/%s" % TRACKER_ID,
      downloader = downloader,
      version = VERSION,
      files = [
        ItemInterpolation("%(data_dir)s/%(warc_file_base)s.warc.gz")
      ],
      rsync_target_source_path = ItemInterpolation("%(data_dir)s/"),
      rsync_extra_args = [
        "--recursive",
        "--partial",
        "--partial-dir", ".rsync-tmp"
      ]
    ),
  ),
  SendDoneToTracker(
    tracker_url = "http://tracker.archiveteam.org/%s" % TRACKER_ID,
    stats = ItemValue("stats")
  )
)

