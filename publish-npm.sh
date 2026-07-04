#!/bin/bash
set -e

echo "==================== NPM 作用域包 @levisli/dlc-mcp 发布脚本 ===================="
OFFICIAL_REG="https://registry.npmjs.org/"
NPM_USERCONFIG_ARG=()
TMP_NPMRC=""

cleanup() {
  if [ -n "$TMP_NPMRC" ] && [ -f "$TMP_NPMRC" ]; then
    rm -f "$TMP_NPMRC"
  fi
}
trap cleanup EXIT

if [ -n "${NPM_TOKEN:-}" ]; then
  TMP_NPMRC=$(mktemp)
  printf 'registry=%s\n//registry.npmjs.org/:_authToken=${NPM_TOKEN}\n' "$OFFICIAL_REG" > "$TMP_NPMRC"
  chmod 600 "$TMP_NPMRC"
  NPM_USERCONFIG_ARG=(--userconfig "$TMP_NPMRC")
  echo "✅ 检测到 NPM_TOKEN，将使用临时 npmrc 发布"
fi

# 1. 校验发布源必须是官方仓库
CURR_REG=$(npm "${NPM_USERCONFIG_ARG[@]}" config get registry)
if [ "$CURR_REG" != "$OFFICIAL_REG" ]; then
  echo "❌ 当前非官方npm源，禁止发布"
  echo "当前源: $CURR_REG"
  echo "修复命令：npm config set registry $OFFICIAL_REG"
  exit 1
fi
echo "✅ npm官方源校验通过"

# 2. 校验本地已登录npm账号
echo -e "\n【校验登录状态】"
npm "${NPM_USERCONFIG_ARG[@]}" whoami
if [ $? -ne 0 ]; then
  echo "❌ 本地未登录npm，执行 npm login 登录后重试，或传入 NPM_TOKEN"
  exit 1
fi
echo "✅ 登录校验成功"

# 3. 读取包信息并校验包名
PKG_NAME=$(node -p "require('./package.json').name")
TARGET_PKG="@levisli/dlc-mcp"
echo -e "\n【校验包名】本地package.json包名：$PKG_NAME"

if [ "$PKG_NAME" != "$TARGET_PKG" ]; then
  echo "❌ 包名不匹配！要求：$TARGET_PKG"
  exit 1
fi
echo "✅ 包名 @levisli/dlc-mcp 校验通过"

# 4. 跳过打包（无build脚本，按需取消注释启用编译）
echo -e "\n【跳过打包构建，无build脚本】"
# npm run build
# tsc

# 5. 检测线上是否存在该包
echo -e "\n【检测线上包是否存在】"
PACKAGE_EXISTS=0
if npm "${NPM_USERCONFIG_ARG[@]}" view "$PKG_NAME" >/dev/null 2>&1; then
  PACKAGE_EXISTS=1
  echo "⚠️ 线上已存在 @levisli/dlc-mcp，本次为版本更新"
  read -p "确认继续升级版本发布？(y/n) " CONFIRM
  if [ "$CONFIRM" != "y" ]; then
    echo "已终止发布流程"
    exit 0
  fi
else
  echo "✅ 全新作用域包，首次发布，将使用 package.json 当前版本"
fi

# 6. 已存在包才选择版本升级规则；首次发布不强制改版本
if [ "$PACKAGE_EXISTS" -eq 1 ]; then
  echo -e "\n【选择版本更新类型】"
  echo "1. patch 小修复 1.0.0 → 1.0.1"
  echo "2. minor 新增功能 1.0.1 → 1.1.0"
  echo "3. major 不兼容大更新 1.1.0 → 2.0.0"
  read -p "输入 1/2/3 ：" VER_OP
  case $VER_OP in
    1) npm version patch --no-git-tag-version ;;
    2) npm version minor --no-git-tag-version ;;
    3) npm version major --no-git-tag-version ;;
    *) echo "输入错误，退出"; exit 1 ;;
  esac
fi
NEW_VER=$(node -p "require('./package.json').version")
echo "✅ 发布版本：$PKG_NAME@$NEW_VER"

echo -e "\n【开始发布公共作用域包】"
if [ -n "${NPM_TOKEN:-}" ]; then
  echo "使用 NPM_TOKEN 发布，不会把 token 写入项目或全局 ~/.npmrc。"
else
  echo "如果 npm 要求 OTP，请按 npm 终端提示输入邮箱或验证器里的验证码。"
fi
npm "${NPM_USERCONFIG_ARG[@]}" publish --access public

echo -e "\n🎉 发布成功！访问地址：https://www.npmjs.com/package/$PKG_NAME"
