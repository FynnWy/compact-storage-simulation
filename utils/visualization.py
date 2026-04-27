# # visualization.py
# import matplotlib.pyplot as plt
# import matplotlib.cm as cm  # <-- Explicit import for colormaps
# import numpy as np

# def plot_3d_storage_grid(engine, title="Storage Grid 3D View"):
#     """
#     Creates a 3D bar chart representing the heights of the bin stacks in the grid.
#     """
#     fig = plt.figure(figsize=(10, 7))
#     ax = fig.add_subplot(111, projection='3d')

#     width = engine.state.grid.width
#     depth = engine.state.grid.depth

#     # Setup the grid coordinates
#     _x = np.arange(width)
#     _y = np.arange(depth)
#     _xx, _yy = np.meshgrid(_x, _y)
    
#     # Flatten the grid coordinates for the 3D bar plot
#     x, y = _xx.ravel(), _yy.ravel()
    
#     # Calculate heights for each stack
#     top = np.zeros_like(x, dtype=float)
#     bottom = np.zeros_like(x, dtype=float)

#     for i, (xi, yi) in enumerate(zip(x, y)):
#         stack = engine.state.grid.get_stack(xi, yi)
#         top[i] = stack.height()

#     width_bar = depth_bar = 0.8

#     # Color code the bars based on their height
#     max_height = max(top.max(), 1)
    
#     # <-- Use the directly imported cm module here
#     colors = cm.viridis(top / max_height)

#     # Plot
#     ax.bar3d(x, y, bottom, width_bar, depth_bar, top, shade=True, color=colors)

#     ax.set_title(title)
#     ax.set_xlabel('Grid Width (X)')
#     ax.set_ylabel('Grid Depth (Y)')
#     ax.set_zlabel('Stack Height (Bins)')

#     plt.tight_layout()
#     plt.show()

import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.patches as mpatches
import numpy as np

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

    # --- CHANGE: Iterate through the grid coordinates ---
    for x in range(width):
        for y in range(depth):
            # Get the stack at this coordinate
            stack = engine.state.grid.get_stack(x, y)
            
            # Iterate through the bins in this stack by index (level)
            # Assuming stack.bins is the list of bin objects
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
    
    # Adjust view angle for better depth perception
    ax.view_init(elev=30, azim=45)

    plt.tight_layout()
    plt.show()


def plot_hot_item_heatmap(engine, title="Hot Items Density"):
    """
    Creates a 2D heatmap showing how many 'hot items' are in each stack.
    Useful for verifying the 'hot_items_top' initialization strategy.
    """
    width = engine.state.grid.width
    depth = engine.state.grid.depth
    
    hot_counts = np.zeros((width, depth))
    hot_bin_set = set(engine.hot_bin_ids)

    for bin_obj in engine.state.bins:
        if bin_obj.bin_id in hot_bin_set:
            if hasattr(bin_obj, 'stack_pos') and bin_obj.stack_pos:
                x, y = bin_obj.stack_pos
                hot_counts[x, y] += 1

    fig, ax = plt.subplots(figsize=(8, 6))
    
    # Plotting the heatmap
    cax = ax.imshow(hot_counts.T, origin='lower', cmap='YlOrRd', interpolation='nearest')
    fig.colorbar(cax, label='Number of Hot Items')
    
    # Add text annotations
    for x in range(width):
        for y in range(depth):
            # <-- Wrap the integer in str() to satisfy the type checker
            ax.text(x, y, str(int(hot_counts[x, y])), ha='center', va='center', color='black')

    ax.set_title(title)
    ax.set_xlabel('Grid Width (X)')
    ax.set_ylabel('Grid Depth (Y)')
    
    # Adjust ticks to match grid dimensions
    ax.set_xticks(np.arange(width))
    ax.set_yticks(np.arange(depth))
    
    plt.tight_layout()
    plt.show()