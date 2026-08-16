import { createApp } from "vue";
import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import App from "./App.vue";
import "./style.css";

// Element Plus ships its own dark-mode variables (a `dark` class on the
// root element), replacing the custom-property `prefers-color-scheme`
// block this dashboard used before the ADR-0032 Element Plus migration.
// Wiring it to the same media query keeps the same "follow the OS theme"
// behavior the dashboard already had.
import "element-plus/theme-chalk/dark/css-vars.css";

function applyColorScheme(query) {
  document.documentElement.classList.toggle("dark", query.matches);
}

const darkModeQuery = window.matchMedia("(prefers-color-scheme: dark)");
applyColorScheme(darkModeQuery);
darkModeQuery.addEventListener("change", applyColorScheme);

createApp(App).use(ElementPlus).mount("#app");
