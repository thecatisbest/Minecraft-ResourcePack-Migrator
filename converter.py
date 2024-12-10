import json
import os
import shutil
import zipfile
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

# Global variables
CURRENT_LANG = "zh"
console = Console()
CustomProgress = None

# Language translations
TRANSLATIONS = {
    "processing_start": {
        "zh": "開始處理檔案...",
        "en": "Starting file processing..."
    },
    "adjusting_structure": {
        "zh": "調整資料夾結構...",
        "en": "Adjusting folder structure..."
    },
    "moving_files": {
        "zh": "移動檔案中",
        "en": "Moving files"
    },
    "processing_files": {
        "zh": "處理檔案中",
        "en": "Processing files"
    },
    "creating_zip": {
        "zh": "建立ZIP檔案...",
        "en": "Creating ZIP file..."
    },
    "compressing_files": {
        "zh": "壓縮檔案中",
        "en": "Compressing files"
    },
    "moved_models": {
        "zh": "已將物品模型從 {} 移動到 {}",
        "en": "Moved item models from {} to {}"
    },
    "process_complete": {
        "zh": "處理完成！",
        "en": "Processing complete!"
    },
    "converted_files_count": {
        "zh": "已轉換 {} 個檔案",
        "en": "Converted {} files"
    },
    "output_file": {
        "zh": "輸出檔案",
        "en": "Output file"
    },
    "current_file": {
        "zh": "當前檔案：{}",
        "en": "Current file: {}"
    },
    "input_dir_error": {
        "zh": "錯誤：找不到輸入資料夾 '{}'",
        "en": "Error: Input directory '{}' not found"
    },
    "error_occurred": {
        "zh": "發生錯誤：{}",
        "en": "Error occurred: {}"
    },
    "file_table_title": {
        "zh": "檔案處理報告",
        "en": "File Processing Report"
    },
    "file_name": {
        "zh": "檔案名稱",
        "en": "File Name"
    },
    "file_type": {
        "zh": "類型",
        "en": "Type"
    },
    "file_status": {
        "zh": "狀態",
        "en": "Status"
    },
    "status_converted": {
        "zh": "已轉換",
        "en": "Converted"
    },
    "status_copied": {
        "zh": "已複製",
        "en": "Copied"
    },
}

def get_text(key, *args):
    """Get translated text"""
    text = TRANSLATIONS.get(key, {}).get(CURRENT_LANG, f"Missing translation: {key}")
    return text.format(*args) if args else text

def get_progress_bar():
    """Create appropriate progress bar based on console type"""
    if hasattr(console, 'status_label') and hasattr(console, 'progress_bar') and CustomProgress:
        return CustomProgress(console)
    return Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(complete_style="green", finished_style="green"),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        TransferSpeedColumn(),
        refresh_per_second=10,
        expand=True
    )

def convert_json_format(input_json, is_item_model=False):
    """
    Convert JSON format for Custom Model Data mode with special handling for bows and crossbows
    
    Args:
        input_json (dict): Original JSON data to convert
        is_item_model (bool): Whether in Item Model mode
        
    Returns:
        dict: Converted JSON in new format
    """
    # Extract and normalize base texture path
    base_texture = input_json.get("textures", {}).get("layer0", "")
    
    if base_texture:
        # Special handling for crossbow_standby
        if base_texture == "item/crossbow_standby":
            base_texture = "item/crossbow"
        elif base_texture == "minecraft:item/crossbow_standby":
            base_texture = "minecraft:item/crossbow"
        
        # Normal path normalization
        if base_texture.startswith("minecraft:item/"):
            base_texture = base_texture
        elif base_texture.startswith("item/"):
            base_texture = f"minecraft:{base_texture}"
        elif not base_texture.startswith("minecraft:"):
            base_texture = f"minecraft:item/{base_texture}"

    # Create basic structure
    new_format = {
        "model": {
            "type": "range_dispatch" if not is_item_model else "model",
            "property": "custom_model_data" if not is_item_model else None,
            "fallback": {"type": "model", "model": base_texture},
            "entries": [] if not is_item_model else None
        }
    }

    # Add display settings if present
    if "display" in input_json:
        new_format["display"] = input_json["display"]

    if "overrides" not in input_json:
        return new_format

    # Detect model type and group overrides
    is_bow = "bow" in base_texture and "crossbow" not in base_texture
    is_crossbow = "crossbow" in base_texture

    # Handle different model types
    if is_crossbow:
        # Group overrides by custom_model_data for crossbow
        cmd_groups = {}
        for override in input_json["overrides"]:
            if "predicate" not in override or "model" not in override:
                continue
                
            predicate = override["predicate"]
            cmd = predicate.get("custom_model_data")
            
            if cmd is None:
                continue
                
            if cmd not in cmd_groups:
                cmd_groups[cmd] = {
                    "base": None,
                    "pulling_states": [],
                    "arrow": None,
                    "firework": None
                }
            
            # Categorize crossbow override
            if "pulling" in predicate:
                pull_value = predicate.get("pull", 0.0)
                cmd_groups[cmd]["pulling_states"].append({
                    "pull": pull_value,
                    "model": override["model"]
                })
            elif "charged" in predicate:
                if predicate.get("firework", 0):
                    cmd_groups[cmd]["firework"] = override["model"]
                else:
                    cmd_groups[cmd]["arrow"] = override["model"]
            else:
                cmd_groups[cmd]["base"] = override["model"]
        
        # Create crossbow entries
        for cmd, group in cmd_groups.items():
            pulling_states = sorted(group["pulling_states"], key=lambda x: x.get("pull", 0))
            base_model = group["base"] or pulling_states[0]["model"] if pulling_states else base_texture
            
            entry = {
                "threshold": int(cmd),
                "model": {
                    "type": "minecraft:condition",
                    "property": "minecraft:using_item",
                    "on_false": {
                        "type": "minecraft:select",
                        "property": "minecraft:charge_type",
                        "fallback": {
                            "type": "minecraft:model",
                            "model": base_model
                        },
                        "cases": []
                    },
                    "on_true": {
                        "type": "minecraft:range_dispatch",
                        "property": "minecraft:crossbow/pull",
                        "fallback": {
                            "type": "minecraft:model",
                            "model": pulling_states[0]["model"] if pulling_states else base_model
                        },
                        "entries": []
                    }
                }
            }

            # Add ammunition cases
            cases = entry["model"]["on_false"]["cases"]
            if group["arrow"]:
                cases.append({
                    "model": {
                        "type": "minecraft:model",
                        "model": group["arrow"]
                    },
                    "when": "arrow"
                })
            if group["firework"]:
                cases.append({
                    "model": {
                        "type": "minecraft:model",
                        "model": group["firework"]
                    },
                    "when": "rocket"
                })

            # Add pulling states
            if pulling_states:
                entries = entry["model"]["on_true"]["entries"]
                for state in pulling_states[1:]:
                    entries.append({
                        "threshold": state.get("pull", 0.0),
                        "model": {
                            "type": "minecraft:model",
                            "model": state["model"]
                        }
                    })

            new_format["model"]["entries"].append(entry)

    elif is_bow:
        # Group overrides by custom_model_data for bow
        cmd_groups = {}
        
        for override in input_json["overrides"]:
            if "predicate" not in override or "model" not in override:
                continue
                
            predicate = override["predicate"]
            cmd = predicate.get("custom_model_data")
            
            if cmd is None:
                continue
                
            if cmd not in cmd_groups:
                cmd_groups[cmd] = {
                    "base": None,
                    "pulling_states": []
                }
            
            if "pulling" in predicate:
                pull_value = predicate.get("pull", 0.0)
                cmd_groups[cmd]["pulling_states"].append({
                    "pull": pull_value,
                    "model": override["model"]
                })
            else:
                cmd_groups[cmd]["base"] = override["model"]
        
        # Create bow entries
        for cmd, group in cmd_groups.items():
            pulling_states = sorted(group["pulling_states"], key=lambda x: x.get("pull", 0))
            base_model = group["base"] or pulling_states[0]["model"] if pulling_states else base_texture
            
            if base_model:
                entry = {
                    "threshold": int(cmd),
                    "model": {
                        "type": "minecraft:condition",
                        "property": "minecraft:using_item",
                        "on_false": {
                            "type": "minecraft:model",
                            "model": base_model
                        },
                        "on_true": {
                            "type": "minecraft:range_dispatch",
                            "property": "minecraft:use_duration",
                            "scale": 0.05,
                            "fallback": {
                                "type": "minecraft:model",
                                "model": base_model
                            },
                            "entries": []
                        }
                    }
                }
                
                # Add pulling states
                if pulling_states:
                    for state in pulling_states:
                        if state["model"] != base_model:  # Skip if it's the same as base model
                            entry["model"]["on_true"]["entries"].append({
                                "threshold": state.get("pull", 0.0),
                                "model": {
                                    "type": "minecraft:model",
                                    "model": state["model"]
                                }
                            })
                
                new_format["model"]["entries"].append(entry)

    else:
        # Handle normal items
        for override in input_json["overrides"]:
            if "predicate" in override and "custom_model_data" in override["predicate"]:
                entry = {
                    "threshold": int(override["predicate"]["custom_model_data"]),
                    "model": {
                        "type": "model",
                        "model": override["model"]
                    }
                }
                new_format["model"]["entries"].append(entry)

    return new_format

def convert_item_model_format(json_data, output_path):
    """
    Convert JSON format for Item Model mode with special handling for bows and crossbows
    
    Args:
        json_data (dict): Original JSON data containing model overrides
        output_path (str): Base path for output files
    """
    if "overrides" not in json_data or not json_data["overrides"]:
        return None

    # Group overrides by custom_model_data
    cmd_groups = {}
    base_texture = json_data.get("textures", {}).get("layer0", "")
    is_bow = "bow" in base_texture and "crossbow" not in base_texture
    is_crossbow = "crossbow" in base_texture

    if is_bow or is_crossbow:
        # First find the base model path for each CMD
        for override in json_data["overrides"]:
            if "predicate" in override and "custom_model_data" in override["predicate"]:
                cmd = override["predicate"]["custom_model_data"]
                model_path = override["model"]
                predicate = override["predicate"]

                # Initialize group if not exists
                if cmd not in cmd_groups:
                    cmd_groups[cmd] = {
                        "base": model_path if "pulling" not in predicate and "charged" not in predicate else None,
                        "pulling_states": [],
                        "arrow": None,
                        "firework": None
                    }

                # Group other states for this CMD
                if "pulling" in predicate:
                    if "pull" in predicate:
                        cmd_groups[cmd]["pulling_states"].append({
                            "pull": predicate["pull"],
                            "model": override["model"]
                        })
                elif "charged" in predicate:
                    if predicate.get("firework", 0):
                        cmd_groups[cmd]["firework"] = override["model"]
                    else:
                        cmd_groups[cmd]["arrow"] = override["model"]

        # Process each group that has a base model
        for cmd, group in cmd_groups.items():
            if not group["base"]:
                continue

            if is_crossbow:
                # Create crossbow JSON structure
                crossbow_json = {
                    "model": {
                        "type": "minecraft:condition",
                        "property": "minecraft:using_item",
                        "on_false": {
                            "type": "minecraft:select",
                            "property": "minecraft:charge_type",
                            "fallback": {
                                "type": "minecraft:model",
                                "model": group["base"]
                            },
                            "cases": []
                        },
                        "on_true": {
                            "type": "minecraft:range_dispatch",
                            "property": "minecraft:crossbow/pull",
                            "fallback": {
                                "type": "minecraft:model",
                                "model": group["pulling_states"][0]["model"] if group["pulling_states"] else group["base"]
                            },
                            "entries": []
                        }
                    }
                }

                # Add ammunition cases
                cases = crossbow_json["model"]["on_false"]["cases"]
                if group["arrow"]:
                    cases.append({
                        "model": {
                            "type": "minecraft:model",
                            "model": group["arrow"]
                        },
                        "when": "arrow"
                    })
                if group["firework"]:
                    cases.append({
                        "model": {
                            "type": "minecraft:model",
                            "model": group["firework"]
                        },
                        "when": "rocket"
                    })

                # Add pulling states
                pulling_states = sorted(group["pulling_states"], key=lambda x: x["pull"])
                if len(pulling_states) > 1:  # Skip first state as it's used in fallback
                    for state in pulling_states[1:]:
                        crossbow_json["model"]["on_true"]["entries"].append({
                            "threshold": state["pull"],
                            "model": {
                                "type": "minecraft:model",
                                "model": state["model"]
                            }
                        })

                # Save crossbow JSON
                if ":" in group["base"]:
                    namespace, path = group["base"].split(":", 1)
                    file_name = os.path.join(output_path, namespace, path) + ".json"
                else:
                    file_name = os.path.join(output_path, group["base"] + ".json")
                
                os.makedirs(os.path.dirname(file_name), exist_ok=True)
                with open(file_name, 'w', encoding='utf-8') as f:
                    json.dump(crossbow_json, f, indent=2)

            else:  # bow
                # Create bow JSON structure
                bow_json = {
                    "model": {
                        "type": "minecraft:condition",
                        "property": "minecraft:using_item",
                        "on_false": {
                            "type": "minecraft:model",
                            "model": group["base"]
                        },
                        "on_true": {
                            "type": "minecraft:range_dispatch",
                            "property": "minecraft:use_duration",
                            "scale": 0.05,
                            "fallback": {
                                "type": "minecraft:model",
                                "model": group["base"]
                            },
                            "entries": []
                        }
                    }
                }

                # Add pulling states
                pulling_states = sorted(group["pulling_states"], key=lambda x: x["pull"])
                for state in pulling_states:
                    if state["model"] != group["base"]:  # Skip if it's the same as base model
                        bow_json["model"]["on_true"]["entries"].append({
                            "threshold": state["pull"],
                            "model": {
                                "type": "minecraft:model",
                                "model": state["model"]
                            }
                        })

                # Save bow JSON
                if ":" in group["base"]:
                    namespace, path = group["base"].split(":", 1)
                    file_name = os.path.join(output_path, namespace, path) + ".json"
                else:
                    file_name = os.path.join(output_path, group["base"] + ".json")
                
                os.makedirs(os.path.dirname(file_name), exist_ok=True)
                with open(file_name, 'w', encoding='utf-8') as f:
                    json.dump(bow_json, f, indent=2)

    else:
        # Handle normal items
        for override in json_data["overrides"]:
            if "predicate" in override and "custom_model_data" in override["predicate"]:
                model_path = override["model"]
                if ":" in model_path:
                    namespace, path = model_path.split(":", 1)
                    file_name = os.path.join(output_path, namespace, path) + ".json"
                else:
                    file_name = os.path.join(output_path, model_path + ".json")
                
                os.makedirs(os.path.dirname(file_name), exist_ok=True)
                
                new_json = {
                    "model": {
                        "type": "model",
                        "model": model_path
                    }
                }
                
                with open(file_name, 'w', encoding='utf-8') as f:
                    json.dump(new_json, f, indent=2)

def process_directory(input_dir, output_dir, mode="cmd"):
    """Process directory in specified mode"""
    processed_files = []
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Copy all files first
    for root, dirs, files in os.walk(input_dir):
        relative_path = os.path.relpath(root, input_dir)
        output_root = os.path.join(output_dir, relative_path)
        os.makedirs(output_root, exist_ok=True)
        
        for file in files:
            input_file = os.path.join(root, file)
            output_file = os.path.join(output_root, file)
            relative_path = os.path.relpath(input_file, input_dir)
            
            try:
                shutil.copy2(input_file, output_file)
                if not file.lower().endswith('.json'):
                    processed_files.append({
                        "path": relative_path,
                        "type": "Other",
                        "status": get_text("status_copied")
                    })
            except Exception as e:
                console.print(f"[red]{get_text('error_occurred', str(e))}[/red]")

    # Process JSON files
    json_files = []
    if mode == "item_model":
        models_item_dir = os.path.join(output_dir, "assets", "minecraft", "models", "item")
        if os.path.exists(models_item_dir):
            json_files = [os.path.join(models_item_dir, f) for f in os.listdir(models_item_dir)
                         if f.lower().endswith('.json')]
    else:
        for root, _, files in os.walk(input_dir):
            for file in files:
                if file.lower().endswith('.json'):
                    json_files.append(os.path.join(root, file))

    with get_progress_bar() as progress:
        task = progress.add_task(get_text("processing_files"), total=len(json_files))
        
        for json_file in json_files:
            relative_path = os.path.relpath(json_file, input_dir)
            
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    json_data = json.load(f)
                
                if "overrides" in json_data and any("custom_model_data" in o.get("predicate", {}) 
                                                  for o in json_data.get("overrides", [])):
                    converted_data = convert_json_format(json_data, mode == "item_model")
                    
                    output_file = os.path.join(output_dir, relative_path)
                    with open(output_file, 'w', encoding='utf-8') as f:
                        json.dump(converted_data, f, indent=4)
                    
                    processed_files.append({
                        "path": relative_path,
                        "type": "JSON",
                        "status": get_text("status_converted")
                    })
                else:
                    processed_files.append({
                        "path": relative_path,
                        "type": "JSON",
                        "status": get_text("status_copied")
                    })
                    
            except Exception as e:
                console.print(f"[red]{get_text('error_occurred', str(e))}[/red]")
            
            progress.update(task, advance=1)
    
    return processed_files

def process_directory_item_model(input_dir, output_dir):
    """
    Process directory in Item Model mode
    Only processes files directly in the models/item directory,
    ignoring any files in subdirectories.
    
    Args:
        input_dir (str): Source directory containing files to convert
        output_dir (str): Destination directory for converted files
        
    Returns:
        list: List of processed file information dictionaries
    """
    processed_files = []
    
    # First copy all files to maintain complete structure
    for root, dirs, files in os.walk(input_dir):
        relative_path = os.path.relpath(root, input_dir)
        output_root = os.path.join(output_dir, relative_path)
        
        os.makedirs(output_root, exist_ok=True)
        
        for file in files:
            if hasattr(console, 'status_label'):
                console.print(get_text("current_file", file))
            
            input_file = os.path.join(root, file)
            output_file = os.path.join(output_root, file)
            shutil.copy2(input_file, output_file)
            
            if not file.lower().endswith('.json'):
                processed_files.append({
                    "path": os.path.relpath(input_file, input_dir),
                    "type": "Other",
                    "status": get_text("status_copied")
                })
    
    # Process only direct JSON files in models/item directory
    models_item_dir = os.path.join(output_dir, "assets", "minecraft", "models", "item")
    items_dir = os.path.join(output_dir, "assets", "minecraft", "items")
    
    if os.path.exists(models_item_dir):
        os.makedirs(items_dir, exist_ok=True)
        
        # Get only direct JSON files (not in subdirectories)
        direct_json_files = [f for f in os.listdir(models_item_dir) 
                           if os.path.isfile(os.path.join(models_item_dir, f)) 
                           and f.lower().endswith('.json')]
        
        total_files = len(direct_json_files)
        
        # Set up progress tracking
        with get_progress_bar() as progress:
            task = progress.add_task(get_text("processing_files"), total=total_files)
            
            # Process each direct JSON file
            for file in direct_json_files:
                if hasattr(console, 'status_label'):
                    console.print(get_text("current_file", file))
                
                src_path = os.path.join(models_item_dir, file)
                dst_path = os.path.join(items_dir, file)
                
                try:
                    # Create backup if file exists
                    if os.path.exists(dst_path):
                        backup_path = f"{dst_path}.bak"
                        shutil.move(dst_path, backup_path)
                    
                    # Move file to new location
                    shutil.move(src_path, dst_path)
                    
                    # Process the moved file
                    with open(dst_path, 'r', encoding='utf-8') as f:
                        json_data = json.load(f)
                    
                    if "overrides" in json_data and any("custom_model_data" in o.get("predicate", {}) 
                                                      for o in json_data.get("overrides", [])):
                        convert_item_model_format(json_data, items_dir)
                        os.remove(dst_path)  # Remove the original file after conversion
                        processed_files.append({
                            "path": os.path.relpath(dst_path, output_dir),
                            "type": "JSON",
                            "status": get_text("status_converted")
                        })
                    else:
                        processed_files.append({
                            "path": os.path.relpath(dst_path, output_dir),
                            "type": "JSON",
                            "status": get_text("status_copied")
                        })
                        
                except Exception as e:
                    console.print(f"[red]{get_text('error_occurred', str(e))}[/red]")
                
                progress.update(task, advance=1)
            
            # Only remove models/item if it's empty
            if os.path.exists(models_item_dir) and not os.listdir(models_item_dir):
                shutil.rmtree(models_item_dir)
    
    return processed_files

def create_file_table(processed_files):
    """Create report table"""
    table = Table(
        title=get_text("file_table_title"),
        show_header=True,
        header_style="bold magenta",
        border_style="blue",
        expand=True
    )
    
    table.add_column(get_text("file_name"), style="cyan", ratio=3)
    table.add_column(get_text("file_type"), style="green", justify="center", ratio=1)
    table.add_column(get_text("file_status"), style="yellow", justify="center", ratio=1)
    
    for file_info in processed_files:
        status_style = "green" if file_info["status"] == get_text("status_converted") else "blue"
        table.add_row(
            file_info["path"],
            file_info["type"],
            f"[{status_style}]{file_info['status']}[/{status_style}]"
        )
    
    return table

def adjust_folder_structure(base_dir):
    """
    Adjust the folder structure by moving files from models/item to items
    
    Args:
        base_dir (str): Base directory to adjust structure in
    """
    assets_path = os.path.join(base_dir, "assets", "minecraft")
    models_item_path = os.path.join(assets_path, "models", "item")
    items_path = os.path.join(assets_path, "items")
    
    if os.path.exists(models_item_path):
        # Only count direct files in models/item directory
        total_files = len([f for f in os.listdir(models_item_path) 
                         if os.path.isfile(os.path.join(models_item_path, f))])
        
        if total_files > 0:
            console.print(f"\n[cyan]{get_text('adjusting_structure')}[/cyan]")
            os.makedirs(items_path, exist_ok=True)
            
            with get_progress_bar() as progress:
                task = progress.add_task(get_text("moving_files"), total=total_files)
                
                # Only process files directly in models/item
                for item in os.listdir(models_item_path):
                    src_path = os.path.join(models_item_path, item)
                    
                    # Skip if it's a directory
                    if os.path.isdir(src_path):
                        continue
                        
                    if hasattr(console, 'status_label'):
                        console.print(get_text("current_file", item))
                    
                    dst_path = os.path.join(items_path, item)
                    
                    # Handle existing file
                    if os.path.exists(dst_path):
                        backup_path = f"{dst_path}.bak"
                        shutil.move(dst_path, backup_path)
                    
                    # Move file
                    shutil.move(src_path, dst_path)
                    progress.update(task, advance=1)
            
            # Only remove models/item if it's empty
            if os.path.exists(models_item_path) and not os.listdir(models_item_path):
                shutil.rmtree(models_item_path)
            
            console.print(f"[green]{get_text('moved_models', models_item_path, items_path)}[/green]")

def create_zip(folder_path, zip_path):
    """Create ZIP archive"""
    total_files = sum(len(files) for _, _, files in os.walk(folder_path))
    
    console.print(f"\n[cyan]{get_text('creating_zip')}[/cyan]")
    
    with get_progress_bar() as progress:
        task = progress.add_task(get_text("compressing_files"), total=total_files)
        
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(folder_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arc_name = os.path.relpath(file_path, folder_path)
                    zipf.write(file_path, arc_name)
                    progress.update(task, advance=1)

def main(lang="zh"):
    """Main program entry point"""
    global CURRENT_LANG
    CURRENT_LANG = lang
    
    input_dir = "input"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_output_dir = f"temp_output_{timestamp}"
    zip_filename = f"converted_{timestamp}.zip"
    
    try:
        # Validate input directory
        if not os.path.exists(input_dir):
            console.print(Panel(
                get_text("input_dir_error", input_dir),
                style="red",
                expand=False
            ))
            return False
            
        # Check if input directory is empty
        if not any(os.scandir(input_dir)):
            console.print(Panel(
                get_text("no_files_found", input_dir),
                style="yellow",
                expand=False
            ))
            return False
        
        # Start processing
        console.print(Panel(
            get_text("processing_start"),
            style="cyan",
            expand=False
        ))
        
        # Create temporary directory
        os.makedirs(temp_output_dir, exist_ok=True)
        
        # Process files
        processed_files = process_directory(input_dir, temp_output_dir)
        
        # Adjust folder structure
        adjust_folder_structure(temp_output_dir)
        
        # Create output ZIP file
        create_zip(temp_output_dir, zip_filename)
        
        # Show completion message
        console.print(f"\n[green]{get_text('process_complete')}[/green]")
        
        # Display processing report
        table = create_file_table(processed_files)
        console.print("\n", table)
        
        # Show summary information
        summary_table = Table.grid(expand=True)
        summary_table.add_column(style="cyan", justify="left")
        
        converted_count = sum(1 for f in processed_files if f["status"] == get_text("status_converted"))
        
        summary_table.add_row(
            f"[bold]{get_text('converted_files_count', converted_count)}[/bold]"
        )
        summary_table.add_row(
            f"[bold]{get_text('output_file')}:[/bold] {zip_filename}"
        )
        
        console.print("\n", Panel(
            summary_table,
            border_style="blue",
            expand=False
        ))
        
        return True
        
    except Exception as e:
        console.print(Panel(
            get_text("error_occurred", str(e)),
            style="red",
            expand=False
        ))
        return False
    
    finally:
        # Clean up temporary directory
        if os.path.exists(temp_output_dir):
            try:
                shutil.rmtree(temp_output_dir)
            except Exception:
                pass

if __name__ == "__main__":
    main()