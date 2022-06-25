""" G-HUB auto update """

from libraries.components import Websocket
from libraries.process import Application
from libraries.utilities import process
import argparse
import json
import time


class GhubUpdater:
    """
    This class created for update the G-HUB application using backend API.
    """

    def __init__(self):

        self.app = Application()
        self.app.control_lghub()
        self.backend = Websocket()

    def launch_ghub(self, retry=5) -> None:
        """
        Close and launch the G-HUB application.
        retry: int = Number of times to retry to launch the G-HUB
        retry_interval_time: int = Time seconds to wait before retry
        """
        for number in range(retry):
            try:
                self.app.terminate_all(True)
                time.sleep(10)
                self.app.launch_all(True)
                print("[INFO]: G-HUB launched successfully")
                break
            except Exception as exception:
                print("[EXCEPTION]: ", exception)
                print("[WARNING]: G-HUB doesn't launching. [{}] Retrying again...".format(number + 1))
        else:
            msg = "[ERROR]: Unable to launch the G-HUB"
            print(msg)
            raise RuntimeError(msg)

    def get_build_info(self) -> dict:
        """
        Return current build information data such as channel name, build id and version.
        """
        build_info = dict()
        self.backend.send_message(verb='GET', path="/updates/channel")
        response = json.loads(self.backend.get_message_response_from_bulk('GET', '/updates/channel'))
        build_info['channel'] = response['payload']['name']
        self.backend.send_message(verb='GET', path="/updates/info")
        response = json.loads(self.backend.get_message_response_from_bulk('GET', '/updates/info'))
        build_info['version'] = response['payload']['version']
        build_info['buildId'] = response['payload']['buildId']
        build_info['branch'] = response['payload']['branch']
        return build_info

    def reset_existing_update_process(self) -> None:
        """
        Reset the G-HUB update process and relaunch the G_HUB if already update process running
        """
        update_states = ["CHECKING_FOR_UPDATES", "UPDATE_DOWNLOADING", "UPDATE_UNPACKING", "UPDATE_READY"]
        self.backend.send_message(verb='GET', path='/updates/status')
        response = json.loads(self.backend.get_message_response_from_bulk('GET', '/updates/status', timeout=60))
        if response['payload']['state'] in update_states:
            print("[INFO]: Resetting existing update process")
            self.backend.send_message(verb='SET', path='/updates/reset')
            self.backend.send_message(verb='SET', path='/updates/purge')
            process.kill("lghub_updater")
            time.sleep(10)
            self.launch_ghub()

    def set_channel(self, channel_name: str, password: str = '', access_tokens: str = '') -> None:
        """
        Set the channel name, password and access tokens to update the build.
        channel_name: str = Name of the update channel
        password: str = Channel password
        """
        path = '/updates/channel'
        channel_name = channel_name.strip()
        json_data = json.dumps({"name": channel_name, "password": password})
        self.backend.send_message(verb='SET', path=path, json=json_data)
        self.backend.send_message(verb='GET', path=path)
        response = json.loads(self.backend.get_message_response_from_bulk('GET', path))
        if response['payload']['name'] == channel_name:
            print("[INFO]: [{}] channel has been set successfully".format(channel_name))
        else:
            msg = "[ERROR]: Given channel is [{}] but [{}] channel has been set"
            print(msg.format(channel_name, response['payload']['name']))
            raise RuntimeError(msg.format(channel_name, response['payload']['name']))

    def check_for_update(self):
        """
        Description: Check for update and return new version if update is available else False.
        Raise an error if there is UPDATER_ERROR.
        """
        self.backend.send_message(verb='SET', path='/updates/reset')
        self.backend.send_message(verb='SET', path='/updates/check_now')
        print("[INFO]: Checking for new updates...")
        time.sleep(10)
        self.backend.send_message(verb='GET', path='/updates/status')
        response = json.loads(self.backend.get_message_response_from_bulk('GET', '/updates/status', timeout=60))
        update_state = response['payload']['state']
        if update_state == 'UPDATER_ERROR':
            msg = "[ERROR]: There is updater error in G-HUB. Please check channel name, password and token"
            print(msg)
            raise RuntimeError(msg)
        elif update_state == "CHECKING_FOR_UPDATES":
            msg = "[ERROR]: Taking long time for checking updates"
            print(msg)
            process.kill("lghub_updater")
            time.sleep(10)
            raise RuntimeError(msg)
        elif update_state == 'NO_UPDATES':
            return False
        else:
            self.backend.send_message(verb='GET', path='/updates/next/info')
            response = json.loads(self.backend.get_message_response_from_bulk('GET', '/updates/next/info'))
            return response['payload']['version']

    def download_new_update(self) -> None:
        """
        Download the new update and wait until new update is ready for install.
        """
        self.backend.send_message(verb='SET', path='/updates/download')
        print("[INFO]: Downloading new updates. Please wait...")
        try:
            self.wait_for_update_state("UPDATE_READY")
            print("[INFO]: Update ready to install...")
        except Exception as exception:
            print("[EXCEPTION]: ", exception)
            msg = "[ERROR]: Downloading not completed. Taking long time to download"
            print(msg)
            raise TimeoutError(msg)

    def install_new_update(self) -> None:
        """
        Start installation process and wait until complete it.
        """
        try:
            self.backend.send_message(verb='SET', path='/updates/install')
        except Exception as exception:
            print("[EXCEPTION]: ", exception)
            print("[WARNING]: Install process may not be started. Please make sure G-HUB updated properly")
        print("[INFO]: Installing new updates. Please wait...")
        self.wait_until_backend_disconnected()
        self.wait_until_backend_connected()
        time.sleep(20)
        if self.check_for_update():
            msg = "[ERROR]: New update installation not completed properly. Please check the G-HUB"
            print(msg)
            raise RuntimeError(msg)
        print("[INFO]: New update installed successfully...")

    def wait_until_backend_connected(self, max_time=600):
        """
        Description: Wait for backend connect. Return True if backend connected within given max time
        else raise the TimeoutError error
        """
        start_time = time.time()
        end_time = start_time + max_time
        while end_time > time.time():
            status = self.backend.process.is_not_running
            if status is None:
                return True
        else:
            msg = "[ERROR]: Waited for {} seconds to connect the backend, but it's not connected"
            print(msg.format(max_time))
            raise TimeoutError(msg.format(max_time))

    def wait_until_backend_disconnected(self, max_time=600):
        """
        Description: Wait for backend disconnect. Return True if backend disconnected within given max time
        else raise the TimeoutError error
        """
        start_time = time.time()
        end_time = start_time + max_time
        while end_time > time.time():
            status = self.backend.process.is_not_running
            if status is True:
                return True
        else:
            msg = "[ERROR]: Waited for {} seconds to disconnect the backend, but it's still connected"
            print(msg.format(max_time))
            raise TimeoutError(msg.format(max_time))

    def wait_for_update_state(self, expected_state, max_time=600):
        """
        Description: Wait for server disconnect. Return True if server is disconnected within given max time else False
        """
        start_time = time.time()
        end_time = start_time + max_time
        while end_time > time.time():
            if self.backend.process.is_not_running:
                continue
            try:
                self.backend.send_message(verb='GET', path='/updates/status')
                response = json.loads(self.backend.get_message_response_from_bulk('GET', '/updates/status'))
                state = response['payload']['state']
                if state == expected_state:
                    return True
            except Exception as exception:
                print("[EXCEPTION]: ", exception)
                continue
        else:
            msg = "[ERROR]: Unable to get the [{}] update state".format(expected_state)
            print(msg)
            raise RuntimeError(msg)

    def print_build_info(self, title):
        """
        Print the build information
        """
        build_info = self.get_build_info()
        print("\n========================================= {} =========================================".format(title))
        for key, value in build_info.items():
            print("{}: {}".format(key.upper(), value))
        print("=" * 104)
        print("\n")

    def start(self, channel_name: str, password: str = '', access_tokens: str = '') -> None:
        """
        This is main method to start the update process.
        """
        self.launch_ghub()
        self.reset_existing_update_process()
        self.print_build_info("CURRENT BUILD INFO")
        self.set_channel(channel_name, password, access_tokens)
        new_version = self.check_for_update()
        if new_version:
            self.download_new_update()
            self.install_new_update()
            if new_version == self.get_build_info()['version']:
                print("[INFO]: New G-HUB version {0} is updated successfully...".format(new_version))
                self.print_build_info("NEW BUILD INFO")
        else:
            print("[INFO]: No new update available....")
        self.app.terminate_all(True)


def main():
    """
    Main entry function
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--channel', default='auto_regression',
                        help="G-HUB channel name to update. Default channel is 'auto_regression'")
    parser.add_argument('-p', '--password', default='', help="Channel password. Default value is ''")
    parser.add_argument('-t', '--token', default='', help="Channel access token. Default value is ''")
    args = parser.parse_args()
    updater = GhubUpdater()
    try:
        updater.start(args.channel, args.password, args.token)
    except Exception as exception:
        print("[EXCEPTION]: ", exception)
        print("[WARNING]: There was some problem while updating the G-HUB. Retrying again...")
        updater.start(args.channel, args.password, args.token)
    finally:
        updater.app.terminate_all(True)


if __name__ == '__main__':
    main()
