# waffle-eda

Goal: An automated, claude code compatable tool suite who's purpose is to take an idea from feature proposal to manufacturable design files, with zero intervention from a human on routing or schematic layout. 

Desired Outcome:
 - Take user description of desired features and refine it into a design document (capabilities, size, port layout, etc)
 - Take design document and build out a BOM (bill of materials), constrained by user's cost limits and manufacturer choice
 - Take parts list and build out a schematic (hopefully one a human EE could read and review)
 - Take design document, parts list and manufacturer choice and determine PCB charecteristcs (dimensions, layers, materials, via types, etc)
 - Place and Route loop: taking PCB specifications, schematic, and BOM: 
    - do a parts layout on the board. 
    - route traces
    - apply electric and design rule checks
    - revise as needed until completion, or fail with report of needed changes. 
 - Take completed PCB and BOM to create manufacturing files for upload to vendor.  

 
