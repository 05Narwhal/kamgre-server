function boundsForGeoJSON(geojson) {
    let bounds = new maplibregl.LngLatBounds(geojson.features[0].geometry.coordinates);
    for (let feature of geojson.features)
        for (let coordinate of feature.geometry.coordinates)
            bounds = bounds.extend(coordinate);
    return bounds;
}

function zoomToGeoJSON(map, geojson) {
    let bounds = boundsForGeoJSON(geojson);
    map.fitBounds(bounds, {
        padding: 40
    });
}

function mapOptions(overrides) {
    let opts = {
        container: 'map',
        style: 'https://tiles.derp.si/maps/streets/style.json',
        center: [14.505, 46.051],
        zoom: 7.5,
        minZoom: 6,
        renderWorldCopies: false,
    };
    return Object.assign(opts, overrides);
}