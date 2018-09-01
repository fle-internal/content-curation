#!/usr/bin/env python
#
# These are tests for the ChannelCache class.
#

from django.test import TestCase

from contentcuration.utils.channelcache import ChannelCacher
from contentcuration.models import Channel

from .base import StudioTestCase
from .testdata import channel, node


class ChannelCacherTestCase(StudioTestCase):

    NUM_INITIAL_PUBLIC_CHANNELS = 2

    def setUp(self):
        super(ChannelCacherTestCase, self).setUp()

        self.channels = []
        for _ in range(self.NUM_INITIAL_PUBLIC_CHANNELS):
            c = channel().make_public(bypass_signals=True)
            self.channels.append(c)


    def test_returns_public_channels(self):
        """
        Returns the list of public channels.
        """

        real_channel_ids = sorted([c.id for c in self.channels])
        cached_channel_ids = sorted([c.id for c in ChannelCacher.get_public_channels()])

        assert (real_channel_ids          # the channels we know are public...
                == cached_channel_ids)    # ...should be present in get_public_channels

    def test_new_public_channel_not_in_cache(self):
        """
        Check that our cache is indeed a cache by not returning any new public
        channels created after regenerating our cache.
        """

        # force fill our public channel cache
        ChannelCacher.regenerate_public_channel_cache()
        # create our new channel and bypass signals when creating it
        new_public_channel = channel()
        new_public_channel.make_public(bypass_signals=True)
        # fetch our cached channel list
        cached_channels = ChannelCacher.get_public_channels()
        # make sure our new public channel isn't in the cache
        assert new_public_channel not in cached_channels


class ChannelTokenCacheTestCase(StudioTestCase):
    """
    Tests for caching tokens using the ChannelSpecificCacher proxy object.
    """

    def setUp(self):
        super(ChannelTokenCacheTestCase, self).setUp()
        self.channel = channel()

    def test_channel_get_human_token_returns_token_if_present(self):
        """
        Check that cache.get_human_token() returns the same thing as
        the real channel.get_human_token().
        """
        c = self.channel
        c.make_token()

        ccache = ChannelCacher.for_channel(c)

        assert ccache.get_human_token() == c.get_human_token()

    def test_channel_get_channel_id_token_returns_channel_id_token(self):
        """
        Check that cache.get_channel_id_token() returns the same thing as
        the real channel.get_channel_id_token().
        """
        c = self.channel
        c.make_token()

        ccache = ChannelCacher.for_channel(c)

        assert ccache.get_channel_id_token() == c.get_channel_id_token()


class ChannelResourceCountCacheTestCase(StudioTestCase):

    def setUp(self):
        super(ChannelResourceCountCacheTestCase, self).setUp()

        self.channel = channel()

    def test_get_resource_count_returns_same_as_channel_get_resource_count(self):
        """
        Check that get_resource_count() returns the same thing as
        channel.get_resource_count() when cache is unfilled yet. That should be
        the case on a newly created channel.

        """
        ccache = ChannelCacher.for_channel(self.channel)

        assert ccache.get_resource_count() == self.channel.get_resource_count()

    def test_get_resource_count_is_really_a_cache(self):
        """
        Check that our count is wrong when we insert a new content node.
        """
        ccache = ChannelCacher.for_channel(self.channel)
        # fill our cache with a value first by calling get_resource_count()
        ccache.get_resource_count()
        # add our new content node
        node(
            parent=self.channel.main_tree,
            data={
                "kind_id": "video",
                "node_id": "nicevid",
                "title": "Bad vid",
            }
        )

        # check that our cache's count is now less than the real count
        assert ccache.get_resource_count() < self.channel.get_resource_count()


class ChannelGetDateModifiedCacheTestCase(StudioTestCase):
    """
    Tests for ChannelCacher.get_date_modified()
    """

    def setUp(self):
        super(ChannelGetDateModifiedCacheTestCase, self).setUp()
        self.channel = channel()

    def test_returns_the_same_as_real_get_date_modified(self):
        """
        When called with the cache unfilled, ChannelCacher.get_date_modified()
        should return the same thing as channel.get_date_modified().
        """

        ccache = ChannelCacher.for_channel(self.channel)

        assert ccache.get_date_modified() == self.channel.get_date_modified()

    def test_get_date_modified_really_is_a_cache(self):
        """
        Check that the cache is really a cache by seeing if the cache value is not
        the same as channel.get_date_modified() when we add a new node. If it
        gets updated, then the cache is either too short lived, or it's not
        really a cachd at all!
        """
        ccache = ChannelCacher.for_channel(self.channel)
        # fill the cache by calling get_date_modified once
        ccache.get_date_modified()

        # add a new node to the channel
        node(
            parent=self.channel.main_tree,
            data={
                "node_id": "videoz",
                "title": "new vid",
                "kind_id": "video",
            }
        )

        # check that the cached modified date is not equal to the channel's new
        # modified date
        assert ccache.get_date_modified() <= self.channel.get_date_modified()
