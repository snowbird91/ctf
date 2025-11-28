const VIEW_NAMESPACE = "snowbird91_ctf_site";
const VIEW_KEY = "global_unique_views";
const STORAGE_KEY = "snowbird91-visited";

async function fetchCount(endpoint) {
  try {
    const response = await fetch(
      `https://api.countapi.xyz/${endpoint}/${VIEW_NAMESPACE}/${VIEW_KEY}`
    );
    if (!response.ok) {
      throw new Error("Network response was not ok");
    }
    const data = await response.json();
    return data.value;
  } catch (error) {
    console.error("Failed to fetch view count:", error);
    return null;
  }
}

async function updateViewCount() {
  const display = document.getElementById("unique-views");
  if (!display) return;

  let count;
  if (!localStorage.getItem(STORAGE_KEY)) {
    count = await fetchCount("hit");
    if (count) {
      localStorage.setItem(STORAGE_KEY, "true");
    }
  }

  if (!count) {
    count = await fetchCount("get");
  }

  if (count !== null) {
    display.textContent = `Unique visitors: ${count.toLocaleString()}`;
  } else {
    display.textContent = "Unique visitors: --";
  }
}

document.addEventListener("DOMContentLoaded", updateViewCount);
