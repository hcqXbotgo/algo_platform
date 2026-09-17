# DDR tools

The host application selects and deploys these tools through the DDR entries in
`device_resources.py`.

| Platform | Local tool | Device path | Run mode |
| --- | --- | --- | --- |
| Falcon2 | `ddr_bandwidth.sh` | `/userdata/ddr_bandwidth.sh` | One sample per monitoring interval |
| Falcon | `rk-msch-probe-for-user-64bit-1` | `/userdata/rk-msch-probe-for-user-64bit-1` | Continuous output reader |

When a configured tool is missing or is not executable on the device, the host
uploads it through ADB or SSH/SFTP, applies mode `755`, and verifies it before
starting DDR monitoring.
