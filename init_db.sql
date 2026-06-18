-- yunrun 数据库初始化脚本
-- 首次启动时自动执行，后续启动跳过（数据库已存在）

SET NAMES utf8mb4;
SET CHARACTER SET utf8mb4;

-- 云跑步用户表
CREATE TABLE IF NOT EXISTS `users` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `username` varchar(255) NOT NULL COMMENT '学号',
  `key` varchar(255) NOT NULL COMMENT '密码',
  `date` datetime DEFAULT NULL COMMENT '截至时间',
  `school_name` varchar(255) DEFAULT NULL,
  `token` text,
  `device_id` varchar(64) DEFAULT NULL,
  `device_name` varchar(128) DEFAULT NULL,
  `school_url` varchar(256) DEFAULT NULL,
  `remark` varchar(256) DEFAULT NULL,
  PRIMARY KEY (`username`),
  UNIQUE KEY `id` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 管理员表
CREATE TABLE IF NOT EXISTS `admins` (
  `username` varchar(255) NOT NULL COMMENT '用户名',
  `password` varchar(255) NOT NULL COMMENT '密码',
  `source` varchar(32) DEFAULT NULL,
  PRIMARY KEY (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 设备表
CREATE TABLE IF NOT EXISTS `devices` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 系统配置表
CREATE TABLE IF NOT EXISTS `sys_config` (
  `key` varchar(64) NOT NULL,
  `value` varchar(256) NOT NULL,
  `desc` varchar(128) DEFAULT NULL,
  PRIMARY KEY (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 学校文件夹表
CREATE TABLE IF NOT EXISTS `school_folders` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `school_name` varchar(128) NOT NULL,
  `folder_type` enum('man','woman','default') NOT NULL DEFAULT 'default',
  `folder_name` varchar(128) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_school_type` (`school_name`,`folder_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 云跑配置表
CREATE TABLE IF NOT EXISTS `confg` (
  `yun_host` varchar(255) DEFAULT NULL COMMENT '云运动地址',
  `school_host` varchar(255) DEFAULT NULL COMMENT '学校地址',
  `publickey` varchar(255) DEFAULT NULL,
  `privatekey` varchar(255) DEFAULT NULL,
  `cipherkeyencrypted` varchar(255) DEFAULT NULL,
  `cipherkey` varchar(255) DEFAULT NULL,
  `md5key` varchar(255) DEFAULT NULL,
  `platform` varchar(255) DEFAULT NULL,
  `app_edition` varchar(255) DEFAULT NULL,
  `school_login_url` varchar(255) DEFAULT NULL,
  `school_id` int(11) DEFAULT NULL,
  `url` varchar(255) DEFAULT NULL,
  `notice` varchar(255) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 购买记录表
CREATE TABLE IF NOT EXISTS `buy` (
  `key` varchar(255) DEFAULT NULL,
  `time` int(11) DEFAULT NULL,
  `username` varchar(255) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ========== PU 口袋校园相关表 ==========

-- PU 用户表
CREATE TABLE IF NOT EXISTS `pu_users` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_name` varchar(64) NOT NULL,
  `password` varchar(128) NOT NULL,
  `token` text,
  `uid` bigint(20) DEFAULT NULL COMMENT '口袋校园用户ID',
  `sid` bigint(20) DEFAULT NULL,
  `device` varchar(32) DEFAULT 'pc',
  `college` varchar(128) DEFAULT NULL,
  `email` varchar(128) DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `yunrun_username` varchar(64) DEFAULT NULL,
  `auto_scheduler` tinyint(4) DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_username_sid` (`user_name`,`sid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- PU 报名日志表
CREATE TABLE IF NOT EXISTS `pu_signup_logs` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_name` varchar(64) DEFAULT NULL,
  `activity_id` bigint(20) DEFAULT NULL,
  `activity_title` varchar(256) DEFAULT NULL,
  `join_start_time` varchar(32) DEFAULT NULL,
  `status` varchar(32) DEFAULT NULL,
  `result` text,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `yunrun_username` varchar(64) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- PU 定时任务注册表
CREATE TABLE IF NOT EXISTS `pu_scheduled_keys` (
  `key` varchar(200) NOT NULL,
  `title` varchar(500) DEFAULT '',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- PU 调度器配置表
CREATE TABLE IF NOT EXISTS `pu_scheduler_config` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `key` varchar(64) NOT NULL,
  `value` varchar(256) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `key` (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 插入默认配置
INSERT IGNORE INTO `sys_config` (`key`, `value`, `desc`) VALUES
('notice', '欢迎使用云跑步平台', '系统公告');
