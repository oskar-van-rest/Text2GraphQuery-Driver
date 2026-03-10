-- Schema for social_network_twitter

CREATE TABLE `USER` (
  `user_id`            STRING(MAX) NOT NULL,
  `username`           STRING(MAX),
  `display_name`       STRING(MAX),
  `bio`                STRING(MAX),
  `profile_image_url`  STRING(MAX),
  `created_at`         STRING(MAX),
  `followers_count`    INT64,
  `following_count`    INT64,
  `tweet_count`        INT64,
  `verified_status`    BOOL
) PRIMARY KEY (`user_id`);

CREATE TABLE `TWEET` (
  `tweet_id`           STRING(MAX) NOT NULL,
  `content`            STRING(MAX),
  `created_at`         STRING(MAX),
  `like_count`         INT64,
  `retweet_count`      INT64,
  `reply_count`        INT64,
  `view_count`         INT64,
  `language`           STRING(MAX),
  `is_sensitive`       BOOL
) PRIMARY KEY (`tweet_id`);

CREATE TABLE `HASHTAG` (
  `hashtag_id`         STRING(MAX) NOT NULL,
  `tag_text`           STRING(MAX),
  `first_used_at`      STRING(MAX),
  `usage_count`        INT64
) PRIMARY KEY (`hashtag_id`);

CREATE TABLE `TREND` (
  `trend_id`           STRING(MAX) NOT NULL,
  `name`               STRING(MAX),
  `url`                STRING(MAX),
  `promoted_content`   BOOL,
  `query`              STRING(MAX),
  `tweet_volume`       INT64,
  `location`           STRING(MAX),
  `updated_at`         STRING(MAX)
) PRIMARY KEY (`trend_id`);

CREATE TABLE `LIST` (
  `list_id`            STRING(MAX) NOT NULL,
  `name`               STRING(MAX),
  `description`        STRING(MAX),
  `created_at`         STRING(MAX),
  `member_count`       INT64,
  `subscriber_count`   INT64,
  `is_private`         BOOL
) PRIMARY KEY (`list_id`);

CREATE TABLE `MEDIA_ATTACHMENT` (
  `media_id`           STRING(MAX) NOT NULL,
  `media_url`          STRING(MAX),
  `media_type`         STRING(MAX),
  `alt_text`           STRING(MAX),
  `uploaded_at`        STRING(MAX)
) PRIMARY KEY (`media_id`);

CREATE TABLE `LOCATION` (
  `location_id`        STRING(MAX) NOT NULL,
  `name`               STRING(MAX),
  `country_code`       STRING(MAX),
  `woeid`              INT64
) PRIMARY KEY (`location_id`);

CREATE TABLE `USERPOSTSTWEET` (
  `SRC_ID`           STRING(MAX) NOT NULL,
  `DST_ID`           STRING(MAX) NOT NULL,
  `posted_at`          STRING(MAX),
  `device_type`        STRING(MAX),
  `location_coordinates` STRING(MAX),
  FOREIGN KEY (`SRC_ID`) REFERENCES `USER` (`user_id`),
  FOREIGN KEY (`DST_ID`) REFERENCES `TWEET` (`tweet_id`)
) PRIMARY KEY (`SRC_ID`, `DST_ID`);

CREATE TABLE `USERFOLLOWSUSER` (
  `SRC_ID`           STRING(MAX) NOT NULL,
  `DST_ID`           STRING(MAX) NOT NULL,
  `followed_at`        STRING(MAX),
  `notification_preference` STRING(MAX),
  FOREIGN KEY (`SRC_ID`) REFERENCES `USER` (`user_id`),
  FOREIGN KEY (`DST_ID`) REFERENCES `USER` (`user_id`)
) PRIMARY KEY (`SRC_ID`, `DST_ID`);

CREATE TABLE `USERENGAGES_WITHTWEET` (
  `SRC_ID`           STRING(MAX) NOT NULL,
  `DST_ID`           STRING(MAX) NOT NULL,
  `engagement_type`    STRING(MAX),
  `engaged_at`         STRING(MAX),
  `is_organic`         BOOL,
  FOREIGN KEY (`SRC_ID`) REFERENCES `USER` (`user_id`),
  FOREIGN KEY (`DST_ID`) REFERENCES `TWEET` (`tweet_id`)
) PRIMARY KEY (`SRC_ID`, `DST_ID`);

CREATE TABLE `TWEETCONTAINS_HASHTAGHASHTAG` (
  `SRC_ID`           STRING(MAX) NOT NULL,
  `DST_ID`           STRING(MAX) NOT NULL,
  `position_in_tweet`  INT64,
  `is_promoted`        BOOL,
  FOREIGN KEY (`SRC_ID`) REFERENCES `TWEET` (`tweet_id`),
  FOREIGN KEY (`DST_ID`) REFERENCES `HASHTAG` (`hashtag_id`)
) PRIMARY KEY (`SRC_ID`, `DST_ID`);

CREATE TABLE `HASHTAGBELONGS_TO_TRENDTREND` (
  `SRC_ID`           STRING(MAX) NOT NULL,
  `DST_ID`           STRING(MAX) NOT NULL,
  `trend_score`        FLOAT64,
  `rank_position`      INT64,
  FOREIGN KEY (`SRC_ID`) REFERENCES `HASHTAG` (`hashtag_id`),
  FOREIGN KEY (`DST_ID`) REFERENCES `TREND` (`trend_id`)
) PRIMARY KEY (`SRC_ID`, `DST_ID`);

CREATE TABLE `TWEETATTACHES_MEDIAMEDIA_ATTACHMENT` (
  `SRC_ID`           STRING(MAX) NOT NULL,
  `DST_ID`           STRING(MAX) NOT NULL,
  `attached_at`        STRING(MAX),
  `position`           INT64,
  FOREIGN KEY (`SRC_ID`) REFERENCES `TWEET` (`tweet_id`),
  FOREIGN KEY (`DST_ID`) REFERENCES `MEDIA_ATTACHMENT` (`media_id`)
) PRIMARY KEY (`SRC_ID`, `DST_ID`);

CREATE TABLE `TWEETORIGINATES_FROMLOCATION` (
  `SRC_ID`           STRING(MAX) NOT NULL,
  `DST_ID`           STRING(MAX) NOT NULL,
  `geo_tagged_at`      STRING(MAX),
  FOREIGN KEY (`SRC_ID`) REFERENCES `TWEET` (`tweet_id`),
  FOREIGN KEY (`DST_ID`) REFERENCES `LOCATION` (`location_id`)
) PRIMARY KEY (`SRC_ID`, `DST_ID`);

CREATE TABLE `USERMEMBER_OF_LISTLIST` (
  `SRC_ID`           STRING(MAX) NOT NULL,
  `DST_ID`           STRING(MAX) NOT NULL,
  `added_at`           STRING(MAX),
  FOREIGN KEY (`SRC_ID`) REFERENCES `USER` (`user_id`),
  FOREIGN KEY (`DST_ID`) REFERENCES `LIST` (`list_id`)
) PRIMARY KEY (`SRC_ID`, `DST_ID`);

CREATE OR REPLACE PROPERTY GRAPH `social_network_twitter`
  NODE TABLES (`USER`, `TWEET`, `HASHTAG`, `TREND`, `LIST`, `MEDIA_ATTACHMENT`, `LOCATION`)
  EDGE TABLES (
    `USERPOSTSTWEET`
      KEY (`SRC_ID`, `DST_ID`)
      SOURCE KEY (`SRC_ID`) REFERENCES `USER` (`user_id`)
      DESTINATION KEY (`DST_ID`) REFERENCES `TWEET` (`tweet_id`)
      LABEL `POSTS`,
    `USERFOLLOWSUSER`
      KEY (`SRC_ID`, `DST_ID`)
      SOURCE KEY (`SRC_ID`) REFERENCES `USER` (`user_id`)
      DESTINATION KEY (`DST_ID`) REFERENCES `USER` (`user_id`)
      LABEL `FOLLOWS`,
    `USERENGAGES_WITHTWEET`
      KEY (`SRC_ID`, `DST_ID`)
      SOURCE KEY (`SRC_ID`) REFERENCES `USER` (`user_id`)
      DESTINATION KEY (`DST_ID`) REFERENCES `TWEET` (`tweet_id`)
      LABEL `ENGAGES_WITH`,
    `TWEETCONTAINS_HASHTAGHASHTAG`
      KEY (`SRC_ID`, `DST_ID`)
      SOURCE KEY (`SRC_ID`) REFERENCES `TWEET` (`tweet_id`)
      DESTINATION KEY (`DST_ID`) REFERENCES `HASHTAG` (`hashtag_id`)
      LABEL `CONTAINS_HASHTAG`,
    `HASHTAGBELONGS_TO_TRENDTREND`
      KEY (`SRC_ID`, `DST_ID`)
      SOURCE KEY (`SRC_ID`) REFERENCES `HASHTAG` (`hashtag_id`)
      DESTINATION KEY (`DST_ID`) REFERENCES `TREND` (`trend_id`)
      LABEL `BELONGS_TO_TREND`,
    `TWEETATTACHES_MEDIAMEDIA_ATTACHMENT`
      KEY (`SRC_ID`, `DST_ID`)
      SOURCE KEY (`SRC_ID`) REFERENCES `TWEET` (`tweet_id`)
      DESTINATION KEY (`DST_ID`) REFERENCES `MEDIA_ATTACHMENT` (`media_id`)
      LABEL `ATTACHES_MEDIA`,
    `TWEETORIGINATES_FROMLOCATION`
      KEY (`SRC_ID`, `DST_ID`)
      SOURCE KEY (`SRC_ID`) REFERENCES `TWEET` (`tweet_id`)
      DESTINATION KEY (`DST_ID`) REFERENCES `LOCATION` (`location_id`)
      LABEL `ORIGINATES_FROM`,
    `USERMEMBER_OF_LISTLIST`
      KEY (`SRC_ID`, `DST_ID`)
      SOURCE KEY (`SRC_ID`) REFERENCES `USER` (`user_id`)
      DESTINATION KEY (`DST_ID`) REFERENCES `LIST` (`list_id`)
      LABEL `MEMBER_OF_LIST`
  );