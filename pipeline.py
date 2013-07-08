import os
import os.path
import shutil
import time
from distutils.version import StrictVersion

import functools
from tornado.httpclient import AsyncHTTPClient

import seesaw
if StrictVersion(seesaw.__version__) < StrictVersion("0.0.15"):
  raise Exception("This pipeline needs seesaw version 0.0.15 or higher.")

from seesaw.project import Project
from seesaw.config import NumberConfigValue, ConfigInterpolation
from seesaw.item import ItemInterpolation, ItemValue
from seesaw.task import SimpleTask, LimitConcurrent
from seesaw.pipeline import Pipeline
from seesaw.externalprocess import WgetDownload
from seesaw.tracker import GetItemFromTracker, UploadWithTracker, SendDoneToTracker, PrepareStatsForTracker
from seesaw.util import find_executable


WGET_LUA = find_executable("Wget+Lua",
      "GNU Wget 1.14.lua.20130523-9a5c",
    [ "./wget-lua",
      "./wget-lua-warrior",
      "./wget-lua-local",
      "../wget-lua",
      "../../wget-lua",
      "/home/warrior/wget-lua",
      "/usr/bin/wget-lua" ])

if not WGET_LUA:
  raise Exception("No usable Wget+Lua found.")


USER_AGENT = "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:23.0) Gecko/20130430 Firefox/23.0"
VERSION = "20130708.02"


## Begin AsyncPopen fix

import pty
import fcntl
import subprocess
import seesaw.externalprocess
from tornado.ioloop import IOLoop, PeriodicCallback

class AsyncPopenFixed(seesaw.externalprocess.AsyncPopen):
  """
  Start the wait_callback after setting self.pipe, to prevent an infinite spew of
  "AttributeError: 'AsyncPopen' object has no attribute 'pipe'"
  """
  def run(self):
    self.ioloop = IOLoop.instance()
    (master_fd, slave_fd) = pty.openpty()

    # make stdout, stderr non-blocking
    fcntl.fcntl(master_fd, fcntl.F_SETFL, fcntl.fcntl(master_fd, fcntl.F_GETFL) | os.O_NONBLOCK)

    self.master_fd = master_fd
    self.master = os.fdopen(master_fd)

    # listen to stdout, stderr
    self.ioloop.add_handler(master_fd, self._handle_subprocess_stdout, self.ioloop.READ)

    slave = os.fdopen(slave_fd)
    self.kwargs["stdout"] = slave
    self.kwargs["stderr"] = slave
    self.kwargs["close_fds"] = True
    self.pipe = subprocess.Popen(*self.args, **self.kwargs)

    self.stdin = self.pipe.stdin

    # check for process exit
    self.wait_callback = PeriodicCallback(self._wait_for_end, 250)
    self.wait_callback.start()

seesaw.externalprocess.AsyncPopen = AsyncPopenFixed

## End AsyncPopen fix


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

