<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Diagnostic evidence ledger — r3.1
Paths are relative to the extracted archive. This ledger contains metadata/findings only; raw diagnostics and installed files remain excluded from the release ZIP.

| Evidence | Exact lines | Finding |
|---|---|---|
| inventory/verify-python3-task-comms.txt | 1-4 | No discrepancy listed; command exit 0 |
| inventory/verify-task-aprs.txt | 1-4 | No discrepancy listed; command exit 0 |
| inventory/verify-task-console.txt | 1-4 | No discrepancy listed; command exit 0 |
| inventory/verify-task-core-compat.txt | 1-4 | No discrepancy listed; command exit 0 |
| inventory/verify-task-core.txt | 1-4 | No discrepancy listed; command exit 0 |
| inventory/verify-task-launcher.txt | 1-4 | No discrepancy listed; command exit 0 |
| inventory/verify-task-maps.txt | 1-4 | No discrepancy listed; command exit 0 |
| inventory/verify-task-mesh.txt | 1-5 | line 4: ??5??????   /usr/lib/task-mesh/task_mesh/hub/notifier.py |
| inventory/verify-task-resources.txt | 1-4 | No discrepancy listed; command exit 0 |
| inventory/verify-task-sdr.txt | 1-4 | No discrepancy listed; command exit 0 |

## Completeness and source hashes
593 regular installed files, 38 inventory files, one inventory directory = 632 tar members. Extraction has no absolute/parent-traversal member paths. All archive bytes were read by gzip/tar during extraction. Input checksum matches owner-supplied expected value. The diff hunks match the supplied diagnostic after ignoring its final extra empty line. No original sound OGA, Direwolf .conf, full gpsd unit, compat rain-core-admin link/target or package control/maintainer scripts are available here.

The signature index gives hashes for inspected Python modules. Hashes below record the remaining reviewed manifests/diagnostic records without sharing their contents:

| Extracted file | SHA-256 |
|---|---|
| installed/usr/lib/systemd/system/task-core.service | `ff3618ce502ce5c3cccb96695913885eabc46e4412c914dc76782e4eac7928b7` |
| installed/usr/lib/systemd/user/task-mesh-service.service | `ef75cb5e88f316e12e1090952c8ee94c56e67bbdcefb4cddc94906b0a424f5e1` |
| installed/usr/lib/task-core/modules/gps.yaml | `369477eb9868adb8c1bbbc1f5dd4011bbf0b83da9e30d62924833c20e1aad34e` |
| installed/usr/lib/task-core/modules/medical.yaml | `634084433f1dea812245c32d9433351854554a94cbef10e0ef288f0f1f2c616f` |
| installed/usr/lib/task-core/modules/mesh.yaml | `842bf7cdcb5318a36ef44da6f48baba1c487e651e0da4773ac75c13138522b05` |
| installed/usr/lib/task-core/modules/radio.yaml | `e7df827d54cea6f3f0685bac627f025ba65e7c8c32d4a054db02c333644e0f19` |
| installed/usr/lib/task-core/modules/sdr.yaml | `388a0a26b7f51fff28ad32b580490f0da0f6af8e4f2863db3c89a6143fc188a9` |
| installed/usr/lib/task-core/modules/system.yaml | `4b1fddb07d28bd5da5c8ce64a530cc9b09654530f8708f7b08f8795c6b8fa106` |
| installed/usr/lib/task-core/modules/weather.yaml | `6688df604e66c546d1ba99fa578ffa2b853e253c29c9e0b58e183b134dc7ce0f` |
| installed/usr/share/task-launcher/apps.d/030-radio.toml | `09647e4a3d85942de903c3e5a70b9223a480ace89099fcd996407921163e2ab4` |
| inventory/README.txt | `df306bdc2be36e1f7243eb46c3d22cc87d8394930dffbe26da55778711b6464f` |
| inventory/bluetooth-controller.txt | `852841c02e65546389cbe34749a9c31210af8f5c483750414f3798b06aa68543` |
| inventory/bluetooth-info.txt | `96b534682e6eccdbe0ddfce6f5a33cff5d967e805b1572a6527decb867bc06b8` |
| inventory/collected-files.txt | `f93276a2f2dc5022179325bfe4de6f2d2b92ec3ae2629af8d22bd46ee4f4e6f3` |
| inventory/collection-errors.txt | `dc937b59892604f5a86ac96936cd7ff09e25f18ae6b758e8014a24c7fa039e91` |
| inventory/core-status.txt | `7b9664013c674411e247c0f2e70a40e9e2d7d42c45257f00f04448b3802d50ca` |
| inventory/direwolf-process.txt | `904d1839709b659147d69c667f92baf121ec7be9ca8459bf696a84efe0d0fb2b` |
| inventory/files-python3-task-comms.txt | `849f86624c54505c1b1f2f9f1dc55b570c7417b004a9cc6ed79d3d732cd82744` |
| inventory/files-task-aprs.txt | `be221170dc59c664e3247ec67db7c4af61ce879c01bd47c5703bf484ee57ec97` |
| inventory/files-task-console.txt | `089d92585703fa33cadc07904d76a4c648aced12e68f4d74a33630ddbfcc3fa1` |
| inventory/files-task-core-compat.txt | `66aa74c8392ec1b8cc0450437fb539038d1d9d79abb0fba9001b16d342b03cd5` |
| inventory/files-task-core.txt | `ee4d9b0cc4d5247fb0e83a3d864042fa062bd02289d7eeb608be813f5ca0834a` |
| inventory/files-task-launcher.txt | `4fb2b4e6dd49c0f073ed3a7a2ca02265da0476862feb5651130982e67609050d` |
| inventory/files-task-maps.txt | `3c865368666fb0dc9d0b70a66f6f64e016faa29432ca5f3c6ab1a81746fc5360` |
| inventory/files-task-mesh.txt | `e45e84fbb61468f5fdc700e99148eadc56af4ad4190a6a184238634586c2cd2d` |
| inventory/files-task-resources.txt | `dd8868762460238be03a0d86853c060eb58091ca107a7aa3a61f5a9924915026` |
| inventory/files-task-sdr.txt | `fe6dae58ee7b760720131a1eeaf6bc501e6dd9b8d2ff234b73d7b2d836f728f1` |
| inventory/gps-status.txt | `dd5398c9822bba30eb791a961c09c2de9abbe8f064b451bd0a2b7b33d5133877` |
| inventory/important-sha256.txt | `adfde6c6aff02090b306acb3e7c54101cdceb3b9b73f6ae197a37fae9fa31f3f` |
| inventory/listeners.txt | `442124008c3eadc7cc8c6e6c20565cc7b53acd46c8c92b193457d98affce53c7` |
| inventory/mesh-service-unit.txt | `dc43605cd2a486109cb4a234b69ca8b7008932c3a04eb7b56fe0061f98226902` |
| inventory/mesh-status.txt | `40d3d9e3a0b5b9549aecbf681834d1362e6e3e9f9dfdfe0bc5d0628703cc538c` |
| inventory/notifier-audio.diff | `726bb52c9f99aff113b74cbcdf42d02f696a871bf5602498891d2eeab2e9cf8e` |
| inventory/rfcomm.txt | `0f6cd97d933b19e209c6edc32bf558859afb9528031a57399a08b226593bfcc1` |
| inventory/serial-devices.txt | `2e7184d1123f94e9910b6fb30f54bd8115b536c0dfde73aafbf48816a255c10c` |
| inventory/serial-ownership.txt | `af6203eb675c00d0e9ad089e06b8017a9c22d6711d3c4620113f35a5770982bc` |
| inventory/sound-package-copyright.txt | `dacb0bce58872ec8ab61df56ec3e4ca525eebd4d6db0b607e21ec7389bcd4829` |
| inventory/verify-python3-task-comms.txt | `602caf8d9c4b1b72ac3a578dfe1aca077337bd9e93541ae67ff9444f1d9a6505` |
| inventory/verify-task-aprs.txt | `3b59ce7971b6892faa1aa587df16a93970f2d68886f3611321f9c2d601fdbc63` |
| inventory/verify-task-console.txt | `9ab851dbc3ceebb7cf2ab92880fc385dd0513f0368d3894a60be7105a274f001` |
| inventory/verify-task-core-compat.txt | `7b6d50bbd9c9e2a0239a5d9aad1795785cafce121ece54bb4b0f990661bc54ac` |
| inventory/verify-task-core.txt | `40ff80e773659606019f293bdce23d78400b82d16a0a072ca2d99257e829ce40` |
| inventory/verify-task-launcher.txt | `2a10e0d0027463d2e4cb07850e7d56b005e758b6b815b95c140bcf774aa32b71` |
| inventory/verify-task-maps.txt | `f86304f8d23627b2c0b738c23e281c6096499254fdc347f7f429c448979648cb` |
| inventory/verify-task-mesh.txt | `1aaa314b59d8563a297ea68de47730c4197afcef96cc37f85a81e0af2ac2bc20` |
| inventory/verify-task-resources.txt | `e64799ded35cc343c578c9aab8bda0eef8c65a25ac0e4a93daaf44a4e8605eff` |
| inventory/verify-task-sdr.txt | `a64773a72ca142eb46966a45a5dbf2c885d66c1147246fd4eeee5cf6fde28571` |
| inventory/versions.txt | `6c6c85b324e52ddddd028363de723c80e129ae7fab6e92f1b57a5cefb33c1c92` |
