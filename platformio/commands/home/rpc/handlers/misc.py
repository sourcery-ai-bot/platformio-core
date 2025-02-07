# Copyright (c) 2014-present PlatformIO <contact@platformio.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import time

from twisted.internet import defer, reactor  # pylint: disable=import-error

from platformio import app
from platformio.commands.home.rpc.handlers.os import OSRPC


class MiscRPC(object):

    def load_latest_tweets(self, username):
        cache_key = f"piohome_latest_tweets_{str(username)}"
        cache_valid = "7d"
        with app.ContentCache() as cc:
            if cache_data := cc.get(cache_key):
                cache_data = json.loads(cache_data)
                # automatically update cache in background every 12 hours
                if cache_data['time'] < (time.time() - (3600 * 12)):
                    reactor.callLater(5, self._preload_latest_tweets, username,
                                      cache_key, cache_valid)
                return cache_data['result']

        return self._preload_latest_tweets(username, cache_key, cache_valid)

    @staticmethod
    @defer.inlineCallbacks
    def _preload_latest_tweets(username, cache_key, cache_valid):
        result = yield OSRPC.fetch_content(
            f"https://api.platformio.org/tweets/{username}"
        )
        result = json.loads(result)
        with app.ContentCache() as cc:
            cc.set(cache_key,
                   json.dumps({
                       "time": int(time.time()),
                       "result": result
                   }), cache_valid)
        defer.returnValue(result)
