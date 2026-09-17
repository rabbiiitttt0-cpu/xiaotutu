<template>
  <router-view />
</template>

<script setup>
// 移动端：登录页与识图页由路由直接切换，无侧边栏
</script>

<style>
* { box-sizing: border-box; }
html, body, #app { margin: 0; padding: 0; height: 100%; }
body {
  font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
  background: #f7f8fa;
  -webkit-tap-highlight-color: transparent;
}
</style>
