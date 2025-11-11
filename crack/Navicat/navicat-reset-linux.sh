#!/bin/bash
set -x

BASE_CONFIG_PATH=$HOME/.config
NAVICAT_PREMIUM_PATH=$BASE_CONFIG_PATH/navicat/Premium
NAVICAT_SETTING_PATH=$BASE_CONFIG_PATH/navicat/Setting
DCONF_PATH=$BASE_CONFIG_PATH/dconf

# 删除Premium和Setting
if [ -d $BASE_CONFIG_PATH ];then
        if [ -d $NAVICAT_PREMIUM_PATH ];then
            rm -rf $NAVICAT_PREMIUM_PATH
        fi
        if [ -d $NAVICAT_SETTING_PATH ];then
            rm -rf $NAVICAT_SETTING_PATH
        fi
    else
        echo $BASE_CONFIG_PATH '目录不存在'
fi

# 删除dconf
if [ -d $DCONF_PATH ];then
        rm -rf $DCONF_PATH
    else 
        echo $DCONF_PATH '目录不存在'
fi
