export function isDark() {
  return document.documentElement.classList.contains("dark");
}

export function toggleTheme() {
  const dark = !isDark();
  document.documentElement.classList.toggle("dark", dark);
  try {
    localStorage.setItem("theme", dark ? "dark" : "light");
  } catch {
    /* private mode — theme just won't persist */
  }
}
