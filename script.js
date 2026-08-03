(() => {
  "use strict";

  const parameters = new URLSearchParams(window.location.search);
  const gcaiEnabled = (parameters.get("gcai") || "").toLowerCase() === "true";
  const artworkVariant = gcaiEnabled ? "gcai" : "generic";
  const assetDirectory = gcaiEnabled ? "assets/gcai/" : "assets/";
  const displayedPrefix = gcaiEnabled ? "gcai/" : "";
  const artworkDescription = gcaiEnabled ? "GCAI logo" : "geometric pixel mark";

  const assetDetails = {
    sdr: {
      filename: `${displayedPrefix}logo-sdr.png`,
      src: `${assetDirectory}logo-sdr.png`,
      alt: `${artworkDescription}, normal SDR encoding`,
    },
    "sdr-max": {
      filename: `${displayedPrefix}logo-sdr-max.png`,
      src: `${assetDirectory}logo-sdr-max.png`,
      alt: `${artworkDescription}, maximum SDR encoding`,
    },
    hdr: {
      filename: `${displayedPrefix}logo-hdr-pq.avif`,
      src: `${assetDirectory}logo-hdr-pq.avif`,
      alt: `${artworkDescription}, HDR Rec.2020 PQ encoding`,
    },
    tone: {
      filename: `${displayedPrefix}logo-hdr-tonemapped.png`,
      src: `${assetDirectory}logo-hdr-tonemapped.png`,
      alt: `${artworkDescription}, HDR source tone-mapped to SDR`,
    },
  };

  const tileGrid = document.querySelector("#tileGrid");
  const isolationBay = document.querySelector("#isolationBay");
  const isolationImage = document.querySelector("#isolationImage");
  const isolationFilename = document.querySelector("#isolationFilename");
  const isolationCounter = document.querySelector("#isolationCounter");
  const selectedFilename = document.querySelector("#selectedFilename");
  const computedValues = document.querySelector("#computedValues");
  const labelsToggle = document.querySelector("#labelsToggle");
  const isolationToggle = document.querySelector("#isolationToggle");
  const controlStatus = document.querySelector("#controlStatus");
  const surroundLabel = document.querySelector("#surroundLabel");

  let selectedAsset = "sdr";
  let isolationActive = false;

  const orderedTiles = () => Array.from(tileGrid.querySelectorAll(".demo-tile"));

  document.documentElement.dataset.logoVariant = artworkVariant;
  document.querySelector("#artworkName").textContent = gcaiEnabled ? "One GCAI mark" : "One geometric mark";
  document.querySelectorAll("[data-asset-image]").forEach((image) => {
    const details = assetDetails[image.dataset.assetImage];
    image.src = details.src;
    image.alt = details.alt;
  });
  orderedTiles().forEach((tile) => {
    tile.querySelector(".tile-title code").textContent = assetDetails[tile.dataset.asset].filename;
  });
  document.querySelector("#experimentalJpegLink").href = `${assetDirectory}logo-hdr-pq.jpg`;

  const announce = (message) => {
    controlStatus.textContent = "";
    window.requestAnimationFrame(() => {
      controlStatus.textContent = message;
    });
  };

  const updatePositionLabels = () => {
    orderedTiles().forEach((tile, index) => {
      tile.querySelector(".tile-position").textContent = String.fromCharCode(65 + index);
    });
  };

  const selectedTileImage = () => {
    if (isolationActive) return isolationImage;
    return tileGrid.querySelector(`.demo-tile[data-asset="${selectedAsset}"] .demo-image`);
  };

  const inspectionProperties = [
    ["width", "width"],
    ["height", "height"],
    ["opacity", "opacity"],
    ["filter", "filter"],
    ["mix-blend-mode", "mixBlendMode"],
    ["object-fit", "objectFit"],
    ["transform", "transform"],
    ["box-shadow", "boxShadow"],
    ["backdrop-filter", "backdropFilter"],
    ["background-blend-mode", "backgroundBlendMode"],
    ["visibility", "visibility"],
    ["animation-name", "animationName"],
  ];

  const updateInspection = () => {
    const image = selectedTileImage();
    if (!image) return;
    const computed = window.getComputedStyle(image);
    selectedFilename.textContent = assetDetails[selectedAsset].filename;
    computedValues.replaceChildren(
      ...inspectionProperties.map(([label, property]) => {
        const row = document.createElement("div");
        const term = document.createElement("dt");
        const value = document.createElement("dd");
        term.textContent = label;
        value.textContent = computed[property] || "(unsupported)";
        row.append(term, value);
        return row;
      }),
    );
  };

  const setSelectedAsset = (asset) => {
    selectedAsset = asset;
    orderedTiles().forEach((tile) => {
      const selected = tile.dataset.asset === asset;
      tile.dataset.selected = String(selected);
      tile.querySelector(".image-target").setAttribute("aria-pressed", String(selected));
    });
    if (isolationActive) updateIsolation();
    updateInspection();
  };

  const updateIsolation = () => {
    const tiles = orderedTiles();
    const index = Math.max(0, tiles.findIndex((tile) => tile.dataset.asset === selectedAsset));
    const details = assetDetails[selectedAsset];
    isolationImage.src = details.src;
    isolationImage.alt = details.alt;
    isolationFilename.textContent = details.filename;
    isolationCounter.textContent = `${index + 1} of ${tiles.length}`;
    window.requestAnimationFrame(updateInspection);
  };

  const stepIsolation = (direction) => {
    const assets = orderedTiles().map((tile) => tile.dataset.asset);
    const current = assets.indexOf(selectedAsset);
    const next = (current + direction + assets.length) % assets.length;
    setSelectedAsset(assets[next]);
    announce(`Showing ${assetDetails[selectedAsset].filename}, ${next + 1} of ${assets.length}.`);
  };

  orderedTiles().forEach((tile) => {
    tile.querySelector(".image-target").addEventListener("click", () => {
      setSelectedAsset(tile.dataset.asset);
      announce(`Selected ${assetDetails[selectedAsset].filename}.`);
    });
  });

  document.querySelectorAll("[data-background-choice]").forEach((button) => {
    button.addEventListener("click", () => {
      const choice = button.dataset.backgroundChoice;
      document.documentElement.dataset.background = choice;
      document.querySelectorAll("[data-background-choice]").forEach((candidate) => {
        candidate.setAttribute("aria-pressed", String(candidate === button));
      });
      const label = choice === "dark" ? "dark gray" : choice === "mid" ? "mid gray" : "white";
      surroundLabel.textContent = label;
      announce(`Comparison surround changed to ${label}.`);
    });
  });

  labelsToggle.addEventListener("click", () => {
    const hidden = document.documentElement.classList.toggle("labels-hidden");
    labelsToggle.setAttribute("aria-pressed", String(hidden));
    labelsToggle.textContent = hidden ? "Show labels" : "Hide labels";
    announce(hidden ? "Tile labels hidden for a blind comparison." : "Tile labels shown.");
  });

  document.querySelector("#shuffleButton").addEventListener("click", () => {
    const tiles = orderedTiles();
    for (let index = tiles.length - 1; index > 0; index -= 1) {
      const random = new Uint32Array(1);
      window.crypto.getRandomValues(random);
      const swapIndex = random[0] % (index + 1);
      [tiles[index], tiles[swapIndex]] = [tiles[swapIndex], tiles[index]];
    }
    tiles.forEach((tile) => tileGrid.append(tile));
    updatePositionLabels();
    if (isolationActive) updateIsolation();
    announce("Tiles shuffled. Labels and CSS remain unchanged.");
  });

  isolationToggle.addEventListener("click", () => {
    isolationActive = !isolationActive;
    isolationToggle.setAttribute("aria-pressed", String(isolationActive));
    isolationToggle.textContent = isolationActive ? "Show all tiles" : "Isolation mode";
    tileGrid.hidden = isolationActive;
    isolationBay.hidden = !isolationActive;
    if (isolationActive) updateIsolation();
    updateInspection();
    announce(isolationActive ? "Isolation mode enabled." : "All four tiles shown.");
  });

  document.querySelector("#previousButton").addEventListener("click", () => stepIsolation(-1));
  document.querySelector("#nextButton").addEventListener("click", () => stepIsolation(1));

  const highRangeQuery = window.matchMedia("(dynamic-range: high)");
  const updateDynamicRange = () => {
    document.querySelector("#dynamicRangeValue").textContent = highRangeQuery.matches ? "true — HDR indicated" : "false — HDR not indicated";
  };
  updateDynamicRange();
  highRangeQuery.addEventListener?.("change", updateDynamicRange);

  document.querySelector("#pixelRatioValue").textContent = String(window.devicePixelRatio);
  document.querySelector("#colorDepthValue").textContent = `${window.screen.colorDepth} bits`;
  document.querySelector("#userAgentValue").textContent = window.navigator.userAgent;
  const served = window.location.protocol === "http:" || window.location.protocol === "https:";
  document.querySelector("#protocolValue").textContent = served ? `yes — ${window.location.protocol}` : `no — ${window.location.protocol}`;

  const avifProbe = new Image();
  const reportAvif = (supported) => {
    const text = supported ? "decoded successfully" : "decode failed";
    const status = document.querySelector("#avifDecodeStatus");
    status.textContent = supported ? "AVIF decoded in this browser." : "AVIF did not decode in this browser.";
    status.dataset.state = supported ? "pass" : "fail";
    document.querySelector("#capabilityAvifValue").textContent = text;
  };
  avifProbe.onload = () => reportAvif(true);
  avifProbe.onerror = () => reportAvif(false);
  avifProbe.src = `${assetDirectory}logo-hdr-pq.avif?decode-check=${Date.now()}`;

  fetch("assets/manifest.json")
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then((manifest) => {
      const hash = manifest.variants[artworkVariant].assets["logo-hdr-pq.avif"].sha256;
      document.querySelector("#assetHash").textContent = `sha256 ${hash.slice(0, 16)}…`;
    })
    .catch(() => {
      document.querySelector("#assetHash").textContent = "unavailable (serve over HTTP)";
    });

  updatePositionLabels();
  updateInspection();
})();
