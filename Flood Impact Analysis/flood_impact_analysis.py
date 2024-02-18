import ee
import geopy
import folium
import streamlit as st
from datetime import datetime
from geopy.geocoders import Nominatim
from streamlit_folium import folium_static
import matplotlib.pyplot as plt

# Initialize Earth Engine
ee.Initialize()

# Title of the app
st.title('Flood Impact Analysis')

# Define a function to get user inputs for dates
def get_dates():
    before_start = st.date_input('Select start date for before flood event')
    before_end = st.date_input('Select end date for before flood event')
    after_start = st.date_input('Select start date for after flood event')
    after_end = st.date_input('Select end date for after flood event')
    return before_start, before_end, after_start, after_end

# Define a function to get user inputs for location
def get_location():
    st.subheader('Enter the location to analyze (e.g., city)')
    location = st.text_input('Location:')
    return location

# Get user inputs for dates and location
before_start, before_end, after_start, after_end = get_dates()
location = get_location()

# Check if the user has provided the dates and location before proceeding
if before_start and before_end and after_start and after_end and location:
    # Get coordinates of the location using geopy
    geolocator = Nominatim(user_agent="flood-analysis")
    location = geolocator.geocode(location)
    if location:
        latitude = location.latitude
        longitude = location.longitude
    else:
        st.error("Location not found. Please enter a valid location.")
        st.stop()

    # Create a buffer around the location to use as the region of interest (ROI)
    buffer_radius = 10000  # in meters
    ROI = ee.Geometry.Point([longitude, latitude]).buffer(buffer_radius)

    # Load the Sentinel-1 SAR GRD dataset
    s1Collection = ee.ImageCollection('COPERNICUS/S1_GRD') \
        .filterBounds(ROI) \
        .filter(ee.Filter.eq('instrumentMode', 'IW')) \
        .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VH')) \
        .filter(ee.Filter.eq('orbitProperties_pass', 'DESCENDING')) \
        .filter(ee.Filter.eq('resolution_meters', 10)) \
        .select('VH')

    # Filter the Sentinel-1 collection for before and after flood dates and mosaic the images
    beforeCollection = s1Collection.filterDate(str(before_start), str(before_end)).mosaic().clip(ROI)
    afterCollection = s1Collection.filterDate(str(after_start), str(after_end)).mosaic().clip(ROI)

    # A. Speckle Filter
    smoothingRadius = 50

    difference = afterCollection.focal_median(smoothingRadius, 'circle', 'meters') \
        .divide(beforeCollection.focal_median(smoothingRadius, 'circle', 'meters'))

    diffThreshold = 1.25
    flooded = difference.gt(diffThreshold).rename('water').selfMask()

    # B. Mask out permanent/semi-permanent water bodies
    permanentWater = ee.Image("JRC/GSW1_4/GlobalSurfaceWater") \
        .select('seasonality').gte(10).clip(ROI)

    flooded = flooded.where(permanentWater, 0).selfMask()

    # C. Mask out areas with steep slopes
    slopeThreshold = 5
    terrain = ee.Algorithms.Terrain(ee.Image("WWF/HydroSHEDS/03VFDEM"))
    slope = terrain.select('slope')
    flooded = flooded.updateMask(slope.lt(slopeThreshold))

    # D. Remove isolated pixels
    connectedPixelThreshold = 8
    connections = flooded.connectedPixelCount()
    flooded = flooded.updateMask(connections.gt(connectedPixelThreshold))

    # E. Calculate Flood Area
    flood_stats = flooded.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=ROI,
        scale=10,
        maxPixels=1e12
    )

    floodAreaHa = ee.Number(flood_stats.get('water')).divide(10000).round()

    # A. European Space Agency’s landcover dataset
    landcover = ee.ImageCollection("ESA/WorldCover/v200").mosaic()
    lc = landcover.clip(ROI)

    # B. Cropland Exposed
    cropland = lc.select('Map').eq(40).selfMask()
    cropland_affected = flooded.updateMask(cropland).rename('crop')

    # Calculate the area of affected cropland in hectares
    crop_pixelarea = cropland_affected.multiply(ee.Image.pixelArea())
    crop_stats = crop_pixelarea.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=ROI,
        scale=10,
        maxPixels=1e12
    )

    floodAffectedCroplandAreaHa = ee.Number(crop_stats.get('crop')).divide(10000).round()

    # C. Built-up Exposed
    builtup = lc.select('Map').eq(50).selfMask()
    builtup_affected = flooded.updateMask(builtup).rename('builtup')

    # Calculate the area of affected built-up areas in hectares
    builtup_pixelarea = builtup_affected.multiply(ee.Image.pixelArea())
    builtup_stats = builtup_pixelarea.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=ROI,
        scale=10,
        maxPixels=1e12
    )

    floodAffectedBuiltupAreaHa = ee.Number(builtup_stats.get('builtup')).divide(10000).round()

    # D. Population Exposed
    population_count = ee.Image("JRC/GHSL/P2016/POP_GPW_GLOBE_V1/2015").clip(ROI)
    population_exposed = population_count.updateMask(flooded).selfMask()

    stats = population_exposed.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=ROI,
        scale=100,
        maxPixels=1e9,
    )

    numberPeopleExposed = stats.getNumber('population_count').round()
    
    st.write('Flooded Area (Ha)', floodAreaHa.getInfo())
    st.write('Flood Affected Cropland Area (Ha)', floodAffectedCroplandAreaHa.getInfo())
    st.write('Flood Affected Built-up Area (Ha)', floodAffectedBuiltupAreaHa.getInfo())
    st.write('Number of People Exposed', numberPeopleExposed.getInfo())

    #  Display the map with user-selected region and layers
    st.subheader('Map with Flood Analysis')
    m = folium.Map(location=[latitude, longitude], zoom_start=10)

    # Add layers to the map
    folium.TileLayer('OpenStreetMap').add_to(m)
    folium.GeoJson(data=ROI.getInfo(), name='Region of Interest').add_to(m)

    # Add layers for flood analysis
    folium.TileLayer(
        tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
        attr='Google Satellite',
        name='Google Satellite',
        overlay=True,
    ).add_to(m)
    
    folium.TileLayer(
        tiles=flooded.getMapId({'palette': 'blue'})['tile_fetcher'].url_format,
        name='Flooded Area',
        attr='Flooded Area tiles',
        overlay=True,
    ).add_to(m)
    
    folium.TileLayer(
        tiles=cropland_affected.getMapId({'palette': 'green'})['tile_fetcher'].url_format,
        name='Affected Cropland',
        attr='Affected Cropland tiles',
        overlay=True,
    ).add_to(m)
    
    folium.TileLayer(
        tiles=builtup_affected.getMapId({'palette': 'red'})['tile_fetcher'].url_format,
        name='Affected Built-up',
        attr='Affected Built-up tiles',
        overlay=True,
    ).add_to(m)
    
    # Display the map
    folium.LayerControl().add_to(m)
    folium_static(m)

    st.subheader('Percentage of Area Affected')
    total_area = ROI.area().divide(10000).getInfo()  # in hectares
    flooded_percentage = (floodAreaHa.getInfo() / total_area) * 100
    # Calculate the percentage of non-flooded area
    non_flooded_percentage = 100 - flooded_percentage
    # Plot pie chart for the percentage of flooded and non-flooded areas
    labels = ['Flooded Area', 'Non-Flooded Area']
    sizes = [flooded_percentage, non_flooded_percentage]
    colors = ['#ff9999', '#66b3ff']
    explode = (0.1, 0)  # explode the first slice (Flooded Area)

    fig2, ax2 = plt.subplots()
    ax2.pie(sizes, explode=explode, labels=labels, colors=colors, autopct='%1.1f%%', startangle=140)
    ax2.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.

    st.pyplot(fig2)

    # Calculate the total cropland area within the ROI
    cropland_area = cropland.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=ROI,
        scale=10,
        maxPixels=1e12
    )

    # Get the total cropland area within the ROI in square meters
    cropland_area_sqm = cropland_area.get('Map').getInfo()

    if cropland_area_sqm is None:
        st.error("No cropland area found within the specified region.")
        st.stop()

    # Convert the total cropland area to hectares
    cropland_area_ha = cropland_area_sqm / 10000

    # Calculate the percentage of cropland affected by floods
    cropland_percentage = (floodAffectedCroplandAreaHa.getInfo() / cropland_area_ha) * 100

    # Plot pie chart for the percentage of cropland affected by floods
    st.subheader('Percentage of Cropland Affected by Floods')
    labels = ['Affected Cropland', 'Unaffected Cropland']
    sizes = [cropland_percentage, 100 - cropland_percentage]
    colors = ['#ff9999', '#66b3ff']
    explode = (0.1, 0)  # explode 1st slice

    # Plotting the pie chart
    fig, ax = plt.subplots()
    ax.pie(sizes, explode=explode, labels=labels, colors=colors, autopct='%1.1f%%', startangle=140)
    ax.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.

    # Display the pie chart
    st.pyplot(fig)

    # Calculate the total built-up area within the ROI
    builtup_area = builtup.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=ROI,
        scale=10,
        maxPixels=1e12
    )

    # Get the total built-up area within the ROI in square meters
    builtup_area_sqm = builtup_area.get('Map').getInfo()

    if builtup_area_sqm is None:
        st.error("No built-up area found within the specified region.")
        st.stop()

    # Convert the total built-up area to hectares
    builtup_area_ha = builtup_area_sqm / 10000

    # Calculate the percentage of built-up areas affected by floods
    builtup_percentage = (floodAffectedBuiltupAreaHa.getInfo() / builtup_area_ha) * 100

    # Plot pie chart for the percentage of built-up areas affected by floods
    st.subheader('Percentage of Built-up Areas Affected by Floods')
    labels = ['Affected Built-up', 'Unaffected Built-up']
    sizes = [builtup_percentage, 100 - builtup_percentage]
    colors = ['#ff9999', '#66b3ff']
    explode = (0.1, 0)  # explode 1st slice

    # Plotting the pie chart
    fig, ax = plt.subplots()
    ax.pie(sizes, explode=explode, labels=labels, colors=colors, autopct='%1.1f%%', startangle=140)
    ax.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.

    # Display the pie chart
    st.pyplot(fig)

else:
    st.warning('Please select dates and enter a location to analyze.')