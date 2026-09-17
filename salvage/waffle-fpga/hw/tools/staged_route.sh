#!/bin/bash
# Staged routing (D57). Run from the repo root with the pre-route board committed (gen_pcb + bga_escape + plane_vias).
#   stage1   export + route only the DDR3 group and the differential pairs (0.25 mm spacing), merge, length-tune, report
#   stage2   export the rest (stage-1 nets keep their copper but lose their pins, so they stay as obstacles), route, merge everything else,
#            finish (plane vias, power, clean-up, widen, stitch), DRC, report
set -e
HS='^(DDR3_|HDMI_D[0-2]_|HDMI_CLK_|USB_UP_D|HUB_UP_D|HUB_DN[1-4]_D|USB[1-3]_D|J1_D)'
NOT_HS='^(?!(DDR3_|HDMI_D[0-2]_|HDMI_CLK_|USB_UP_D|HUB_UP_D|HUB_DN[1-4]_D|USB[1-3]_D|J1_D))'
FR=/tmp/freerouting-1.9.0.jar
case "$1" in
  stage1-export)
    HS_CLR=0.20 ROUTE_ONLY="$HS" python3 hw/tools/export_dsn.py build/stage1.dsn ;;
  stage1-route)
    xvfb-run -a java -jar $FR -de build/stage1.dsn -do build/stage1.ses -mp 6 -oit 2 > build/stage1.log 2>&1 ;;
  stage1-finish)
    python3 hw/tools/merge_ses_nets.py build/stage1.ses --only "$HS" && python3 hw/tools/ddr3_tune.py && python3 hw/tools/drc_cleanup.py && python3 hw/tools/route_report.py ;;
  stage2-export)
    ROUTE_ONLY="$NOT_HS" python3 hw/tools/export_dsn.py build/stage2.dsn ;;
  stage2-route)
    xvfb-run -a java -jar $FR -de build/stage2.dsn -do build/stage2.ses -mp 6 -oit 5 > build/stage2.log 2>&1 ;;
  stage2-finish)
    python3 hw/tools/merge_ses_nets.py build/stage2.ses --except "$HS" && python3 hw/tools/plane_vias.py && python3 hw/tools/power_widen.py && python3 hw/tools/drc_cleanup.py && python3 hw/tools/widen.py && python3 hw/tools/stitch_vias.py && python3 hw/tools/drc_cleanup.py \
      && python3 -c "import sys; sys.path.insert(0,'hw/tools'); from gen_pcb import inject_stackup, write_project; inject_stackup('hw/waffle.kicad_pcb'); write_project()" \
      && kicad-cli pcb drc --severity-all --format report --output build/drc.rpt hw/waffle.kicad_pcb && python3 hw/tools/route_report.py \
      && for side in top bottom; do kicad-cli pcb render --side $side --zoom 1 --width 1300 --height 1900 --output hw/waffle-board-$side.png hw/waffle.kicad_pcb; done ;;
  *) echo "usage: $0 stage1-export|stage1-route|stage1-finish|stage2-export|stage2-route|stage2-finish"; exit 1 ;;
esac
