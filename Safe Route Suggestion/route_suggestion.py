import streamlit as st
import folium
from streamlit_folium import folium_static
import osmnx as ox
import networkx as nx
import sklearn
import rasterio


def main():
    # Title of the app

    lats = []
    longs = []

    with rasterio.open('ph1.tif') as src:
        # Read the metadata
        transform = src.transform
        # Read pixel coordinates from a text file, excluding the last line
        with open('ph1.txt', 'r') as file:
            line = file.readline()

            line=eval(line)
            last_ele=line[-1]
            line= [eval(line[i]) for i in range(len(line)-1)]
            print(line,last_ele)

        # Convert pixel coordinates to geographic coordinates (latitude and longitude)
        georeferenced_coords = [src.xy(row, col) for row, col in line]
        # Print the converted geographic coordinates
        print("Georeferenced Coordinates:")
        for lat, lon in georeferenced_coords:
            print(f"Latitude: {lat}, Longitude: {lon}")
            
            lats.append(lat)
            longs.append(lon)

    mymap =  folium.Map(location=[sum(lats)/len(lats), sum(longs)/len(longs)], zoom_start=4)

    for i in range(len(lats)):
        folium.Marker(location=[lats[i], longs[i]]).add_to(mymap)


    ox.settings.log_console=True
    ox.settings.use_cache=True

    mode = 'walk'  
    optimizer = 'time'

    st.title('Human Locations')

    # Create a Folium map centered at the mean of coordina

    folium_static(mymap)

    latitude1 = 37.78071
    longitude1 = -122.41445

    place     = 'San Francisco, California, United States'
    graph = ox.graph_from_place(place , network_type = mode)

    orig_node = ox.distance.nearest_nodes(graph, longitude1,latitude1)
    dest_node = ox.distance.nearest_nodes(graph, longs[0],lats[0])
    shortest_route = nx.shortest_path(graph,orig_node,dest_node,weight=optimizer)
    shortest_route_map = ox.plot_route_folium(graph, shortest_route)

    folium.Marker(location=[lats[0], longs[0]]).add_to(shortest_route_map)


    folium_static(shortest_route_map)


if __name__ == "__main__":
    main()
