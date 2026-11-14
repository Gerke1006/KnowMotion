# History data and provenance

`sources.json` is a discoverable registry of official source URLs. Live research must fetch the selected pages and retain retrieval time and evidence; this registry is not a prewritten lesson. UNESCO's pages do not agree on every date (see the Zhang Qian notes), so planning must preserve that uncertainty or use the broader supported period.

`locations.json` records WGS84 point anchors from Wikidata P625, including statement IDs and immutable revision links. Coordinates are approximate modern-place context. They do not establish an ancient city's boundary or the exact route of a historical journey. Geographic facts are CC0 under [Wikidata licensing](https://www.wikidata.org/wiki/Wikidata:Licensing). Match names and region as well as labels: places such as Alexandria have homonyms on different continents.

`portraits.json` lists approved historical artwork and its public-relative asset path. The bundled Zhang Qian subject is a later Mogao mural, not a contemporary portrait; the central mounted figure is Emperor Wu, while Zhang Qian kneels at the left. Keep the full mural legible and show the period/caption. Do not label a crop of the central rider as Zhang Qian. Provenance is [Wikimedia Commons File:Zhang Qian.jpg](https://commons.wikimedia.org/wiki/File:Zhang_Qian.jpg).

The public-domain Natural Earth land polygons and license manifest are in `renderers/remotion/project/public/data/`. These are physical land shapes with no administrative boundaries, not a historical border reconstruction. Licensed mural assets are in the sibling `public/portraits/` directory.
