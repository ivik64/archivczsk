import os
import shutil
import threading
import traceback
import datetime

from Components.config import config, configfile
from Components.Console import Console
from Screens.MessageBox import MessageBox
from skin import loadSkin

from Plugins.Extensions.archivCZSK import _, log, toString, settings
from Plugins.Extensions.archivCZSK.engine.addon import VideoAddon, XBMCAddon
from Plugins.Extensions.archivCZSK.engine.exceptions.updater import UpdateXMLVersionError
from Plugins.Extensions.archivCZSK.engine.tools.task import Task
from Plugins.Extensions.archivCZSK.gui.info import showVideoPlayerInfo
from Plugins.Extensions.archivCZSK.gui.common import showInfoMessage
from Plugins.Extensions.archivCZSK.gui.content import ArchivCZSKContentScreen
from Plugins.Extensions.archivCZSK.compat import DMM_IMAGE

from Plugins.Extensions.archivCZSK.engine.updater import ArchivUpdater


class ArchivCZSK():

    __loaded = False
    __need_restart = False
    __check_update_ts = None
    __check_addon_update_ts = None

    __repositories = {}
    __addons = {}

    @staticmethod
    def isLoaded():
        return ArchivCZSK.__loaded

    @staticmethod
    def load_repositories():
        from engine.repository import Repository
        log.debug('looking for repositories in %s', settings.REPOSITORY_PATH)
        for repo in os.listdir(settings.REPOSITORY_PATH):
            repo_path = os.path.join(settings.REPOSITORY_PATH, repo)
            if os.path.isfile(repo_path):
                continue
            log.debug('found repository %s', repo)
            repo_xml = os.path.join(repo_path, 'addon.xml')
            try:
                repository = Repository(repo_xml)
            except Exception:
                traceback.print_exc()
                log.error('cannot load repository %s, skipping..', repo)
                log.logError('Load repository %s failed, skipping...' % repo)
                continue
            else:
                ArchivCZSK.add_repository(repository)
        ArchivCZSK.__loaded = True

    @staticmethod
    def load_skin():
        try:
            from enigma import getDesktop
            desktop_width = getDesktop(0).size().width()
            log.logDebug("Screen width %s px"%desktop_width)
            if  desktop_width >= 1280:
                if DMM_IMAGE:
                    if desktop_width == 1920:
                        skin_default_path = os.path.join(settings.SKIN_PATH, "default_dmm_fhd.xml")
                    else:
                        skin_default_path = os.path.join(settings.SKIN_PATH, "default_dmm_hd.xml")
                else:
                    if desktop_width == 1920:
                        skin_default_path = os.path.join(settings.SKIN_PATH, "default_fhd.xml")
                    else:
                        skin_default_path = os.path.join(settings.SKIN_PATH, "default_hd.xml")
            else:
                skin_default_path = os.path.join(settings.SKIN_PATH, "default_sd.xml")
            skin_name = config.plugins.archivCZSK.skin.value
            skin_path = os.path.join(settings.SKIN_PATH, skin_name + ".xml")
            if skin_name == 'auto' or not os.path.isfile(skin_path):
                skin_path = skin_default_path
            log.info("loading skin %s" % skin_path)
            log.logDebug("loading skin %s" % skin_path)
            loadSkin(skin_path)
        except:
            log.logError("Load plugin skin failed.\n%s"%traceback.format_exc())
            pass

    @staticmethod
    def get_repository(repository_id):
        return ArchivCZSK.__repositories[repository_id]

    @staticmethod
    def add_repository(repository):
        ArchivCZSK.__repositories[repository.id] = repository

    @staticmethod
    def get_addon(addon_id):
        return ArchivCZSK.__addons[addon_id]

    @staticmethod
    def get_addons():
        return ArchivCZSK.__addons.values()

    @staticmethod
    def get_video_addons():
        return [addon for addon in ArchivCZSK.get_addons() if isinstance(addon, VideoAddon)]

    @staticmethod
    def get_xbmc_addon(addon_id):
        return XBMCAddon(ArchivCZSK.__addons[addon_id])

    @staticmethod
    def has_addon(addon_id):
        return addon_id in ArchivCZSK.__addons

    @staticmethod
    def add_addon(addon):
        ArchivCZSK.__addons[addon.id] = addon


    def __init__(self, session):
        self.session = session
        self.to_update_addons = []
        self.updated_addons = []
        self.first_time = os.path.exists(os.path.join(settings.PLUGIN_PATH, 'firsttime'))

        if ArchivCZSK.__need_restart:
            self.ask_restart_e2()

        elif self.first_time:
            self.opened_first_time()
        elif config.plugins.archivCZSK.archivAutoUpdate.value and self.canCheckUpdate(True):
           self.checkArchivUpdate()
        elif config.plugins.archivCZSK.autoUpdate.value and self.canCheckUpdate(False):
            self.download_commit()
        else:
            self.open_archive_screen()

    def canCheckUpdate(self, archivUpdate):
        limitHour = 2
        try:
            if archivUpdate:
                if ArchivCZSK.__check_update_ts is None:
                    ArchivCZSK.__check_update_ts = datetime.datetime.now()
                    return True
                else:
                    delta = ArchivCZSK.__check_update_ts + datetime.timedelta(hours=limitHour)
                    if datetime.datetime.now() > delta:
                        ArchivCZSK.__check_addon_update_ts = datetime.datetime.now()
                        return True
                    else:
                        return False
            else:
                if ArchivCZSK.__check_addon_update_ts is None:
                    ArchivCZSK.__check_addon_update_ts = datetime.datetime.now()
                    return True
                else:
                    delta = ArchivCZSK.__check_addon_update_ts + datetime.timedelta(hours=limitHour)
                    if datetime.datetime.now() > delta:
                        ArchivCZSK.__check_addon_update_ts = datetime.datetime.now()
                        return True
                    else:
                        return False
        except:
            log.logError("canCheckUpdate failed.\n%s"%traceback.format_exc())
            return True

    def checkArchivUpdate(self):
        try:
            log.logInfo("Checking archivCZSK update...")
            upd = ArchivUpdater(self)
            upd.checkUpdate()
        except:
            if config.plugins.archivCZSK.autoUpdate.value and self.canCheckUpdate(False):
                self.download_commit()
            else:
                self.open_archive_screen()

    def download_commit(self):
        try:
            log.logInfo("Checking addons update...")
            path = os.path.join(os.path.dirname(__file__), 'commit')
            self.__console = Console()
            self.__console.ePopen('curl -kfo %s https://raw.githubusercontent.com/mx3L/archivczsk-doplnky/master/commit' % path, self.check_commit_download)
        except:
            log.logError("Download addons commit failed.")
            self.open_archive_screen()

    def check_commit_download(self, data, retval, extra_args):
        if retval == 0:
            self.check_addon_updates()
        else:
            log.error("commit not downloaded")
            log.logError("Download addons commit return failed.")
            self.open_archive_screen()

    def opened_first_time(self):
        os.remove(os.path.join(settings.PLUGIN_PATH, 'firsttime'))
        text = _("This is the first time you started archivyCZSK") + "\n\n"
        text += _("For optimal usage of this plugin, you need to check") + "\n"
        text += _("if you have all neccessary video plugins installed") + "."
        showInfoMessage(self.session, text, 0, self.open_player_info)


    def open_player_info(self, callback=None):
        showVideoPlayerInfo(self.session, self.download_commit)

    def check_addon_updates(self):
        lock = threading.Lock()
        threads = []
        def check_repository(repository):
            try:
                to_update = repository.check_updates()
                with lock:
                    self.to_update_addons += to_update
            except UpdateXMLVersionError:
                log.logError('cannot retrieve update xml for repository %s'%repository)
                log.error('cannot retrieve update xml for repository %s', repository)
            except Exception:
                traceback.print_exc()
                log.logError('error when checking updates for repository %s.\n%s' %(repository, traceback.format_exc()))
                log.error('error when checking updates for repository %s', repository)
        for repo_key in self.__repositories.keys():
            repository = self.__repositories[repo_key]
            threads.append(threading.Thread(target=check_repository, args=(repository,)))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        update_string = '\n'.join(addon.name for addon in self.to_update_addons)
        if len(self.to_update_addons) > 5:
            update_string = '\n'.join(addon.name for addon in self.to_update_addons[:6])
            update_string += "\n...\n..."

        if update_string != '':
            self.ask_update_addons(update_string)
        else:
            self.open_archive_screen()


    def ask_update_addons(self, update_string):
        self.session.openWithCallback(
                self.update_addons,
                MessageBox,
                "%s %s? (%s)\n\n%s" %(_("Do you want to update"), _("addons"), len(self.to_update_addons), toString(update_string)),
                type = MessageBox.TYPE_YESNO)

    def update_addons(self, callback=None, verbose=True):
        if not callback:
            self.open_archive_screen()
        else:
            updated_string = self._update_addons()
            self.session.openWithCallback(self.ask_restart_e2,
                    MessageBox,
                    "%s (%s/%s):\n\n%s"%(_("Following addons were updated"), len(self.updated_addons), len(self.to_update_addons), toString(updated_string)),
                    type=MessageBox.TYPE_INFO)

    def _update_addons(self):
        for addon in self.to_update_addons:
            updated = False
            try:
                updated = addon.update()
            except Exception:
                traceback.print_exc()
                log.logError("Update addon '%s' failed.\n%s" % (addon.id,traceback.format_exc()))
                continue
            else:
                if updated:
                    self.updated_addons.append(addon)

        update_string = '\n'.join(addon_u.name for addon_u in self.updated_addons)
        if len(self.updated_addons) > 5:
            update_string = '\n'.join(addon.name for addon in self.updated_addons[:6])
            update_string += "\n...\n..."

        return update_string


    def ask_restart_e2(self, callback=None):
        ArchivCZSK.__need_restart = True
        self.session.openWithCallback(self.restart_e2, 
                MessageBox, 
                _("You need to restart E2. Do you want to restart it now?"), 
                type=MessageBox.TYPE_YESNO)


    def restart_e2(self, callback=None):
        if callback:
            from Screens.Standby import TryQuitMainloop
            self.session.open(TryQuitMainloop, 3)

    def open_archive_screen(self, callback=None):
        if not ArchivCZSK.__loaded:
            self.load_repositories()

        # first screen to open when starting plugin,
        # so we start worker thread where we can run our tasks(ie. loading archives)
        Task.startWorkerThread()
        self.session.openWithCallback(self.close_archive_screen, ArchivCZSKContentScreen, self)

    def close_archive_screen(self):
        if not config.plugins.archivCZSK.preload.getValue():
            self.__addons.clear()
            self.__repositories.clear()
            ArchivCZSK.__loaded = False

        self.__console = None
        # We dont need worker thread anymore so we stop it
        Task.stopWorkerThread()

        # finally save all cfg changes - edit by shamman
        configfile.save()

        # clear tmp content by shamman
        filelist = [ f for f in os.listdir("/tmp") if f.endswith(".url") ]
        for f in filelist:
            try:
                os.remove(os.path.join('/tmp', f))
            except OSError:
                continue
        filelist = [ f for f in os.listdir("/tmp") if f.endswith(".png") ]
        for f in filelist:
            try:
                os.remove(os.path.join('/tmp', f))
            except OSError:
                continue
        shutil.rmtree("/tmp/archivCZSK", True)

        if config.plugins.archivCZSK.clearMemory.getValue():
            try:
                with open("/proc/sys/vm/drop_caches", "w") as f:
                    f.write("1")
            except IOError as e:
                log.error('cannot drop caches : %s' % str(e))
