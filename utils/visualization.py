# utils/visualization.py

import matplotlib.cm as cm
import matplotlib.patches as mpatches
import numpy as np
import matplotlib
matplotlib.use('Qt5Agg') 
import matplotlib.pyplot as plt

def plot_3d_storage_grid(engine, title="Detailed Storage Grid"):
    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_subplot(111, projection='3d')

    width = engine.state.grid.width
    depth = engine.state.grid.depth
    
    color_hot = "#ff4d4d"
    color_cold = "#4d94ff"
    hot_bin_set = set(engine.hot_bin_ids)

    dx = dy = 0.8
    dz = 0.95 

    for x in range(width):
        for y in range(depth):
            stack = engine.state.grid.get_stack(x, y)
            
            for z, bin_obj in enumerate(stack.bins):
                
                is_hot = bin_obj.bin_id in hot_bin_set
                color = color_hot if is_hot else color_cold
                
                # Plot the bin at its current grid x, y and calculated z
                ax.bar3d(x, y, z, dx, dy, dz, 
                         color=color, 
                         edgecolor='black', 
                         linewidth=0.5,
                         alpha=0.8)

    # Create a custom legend
    hot_patch = mpatches.Patch(color=color_hot, label='Hot Item (High Demand)')
    cold_patch = mpatches.Patch(color=color_cold, label='Cold Item (Low Demand)')
    ax.legend(handles=[hot_patch, cold_patch], loc='upper right', title="Bin Status")

    ax.set_title(title)
    ax.set_xlabel('Grid Width (X)')
    ax.set_ylabel('Grid Depth (Y)')
    ax.set_zlabel('Stack Level (Z)')
    
    ax.view_init(elev=30, azim=45)
    ax.set_box_aspect((width, depth, max(stack.height() for stack in engine.state.grid.stacks.values() if stack.height() > 0) or 1))

    plt.tight_layout()
    plt.show()