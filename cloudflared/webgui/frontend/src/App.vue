<template>
  <div class="min-h-screen bg-gray-50">
    <NavBar />
    <main class="mx-auto max-w-5xl px-4 py-8">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import NavBar from '@/components/NavBar.vue'
</script>
