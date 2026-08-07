# Changelog

## [0.5.1](https://github.com/peterschwps/SAP-Datasphere-CLI/compare/v0.5.0...v0.5.1) (2026-08-07)


### Features

* **tui:** add clean interface ([#27](https://github.com/peterschwps/SAP-Datasphere-CLI/issues/27)) ([38494f4](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/38494f4509b32a02ea3b8c4138a526c1210e4673))

## [0.5.0](https://github.com/peterschwps/SAP-Datasphere-CLI/compare/v0.4.0...v0.5.0) (2026-08-07)


### ⚠ BREAKING CHANGES

* removed token persistence from the client
* restructured the client into endpoint and workflow layers ([#10](https://github.com/peterschwps/SAP-Datasphere-CLI/issues/10))
* unified task input and per-run result folders

### Features

* **actions:** report the outcome of every batch item ([7d51a08](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/7d51a084bfb61da050a7ce0c24e54b71d03af98b))
* add new status TABLE_NOT_FOUND when configuring remote table statistics ([c08e3a5](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/c08e3a5324c8f0b07d45a81342d7f68258cae61b))
* add non-interactive authentication and workflow timeouts ([#15](https://github.com/peterschwps/SAP-Datasphere-CLI/issues/15)) ([9ad1df1](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/9ad1df198d2887c2c4e8a4aa6631110a5edf5707))
* added all available commands as required by the CLI ([c42226d](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/c42226d35725753738e619fde532d13b38672938))
* added analytical models resource ([f974933](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/f974933345d3f37de9262ed98882e8a01603b30a))
* added async datasphere client ([86c90fe](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/86c90fe6bb862c10f9e9c75759ccd3414d9ba61c))
* added command registry ([7db4aa3](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/7db4aa39ae5e10a4ae70658703b4cbbf1880932d))
* added command to start task chain directly from the command line ([9b7813a](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/9b7813a9a240a00d5e9168b782f39594771c9244))
* added CommandContext class that holds all runtime dependencies ([67119c7](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/67119c7682e19f5df0632a12505d0ffa8b0e906e))
* added configuration and exceptions ([a6b55ca](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/a6b55ca5b7fd977944beb5afe631ed2692055789))
* added data models ([6b18eaa](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/6b18eaa1e8171c5d4147099d32446edb1da62ea7))
* added incremental result callbacks to all view batch methods ([f78cff6](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/f78cff6e4b3c7405f6647773709b625ffcbea343))
* added option to report completion of batch items during runtime ([ccdc2f4](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/ccdc2f42901c327e308726ac8f5a7c4235f9c87f))
* added option to run commands directly from the command line ("non-interactive mode") ([4efa341](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/4efa34189f17cc23ef7be13d155925f3523e2313))
* added remote tables resource ([7c5f9c0](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/7c5f9c07d7f536ee67d17684b0768d04a01c65e7))
* added storage of the access and refresh tokens in the OS credential store ([071572b](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/071572b99a31807854f6feeb45be307decd41316))
* added task chains resource ([387dd42](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/387dd42ffa6e62e18d686ef4af36d4709b3f58c3))
* added token store and oauth authentication ([9acf487](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/9acf4873ea58a7e125bccdfecbcebac9914d02ad))
* added views resource ([137d1eb](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/137d1ebd3efc5a3ef58ff75669fb86d6c0a2f3e3))
* **auth:** report the end of every login step ([5f95a64](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/5f95a6465ad9c4c84683fb82ddd45d75108bc7fa))
* **cli:** switch the HTTP logging on from the environment ([581059f](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/581059f62b5ed6c2d72e4c8e8ce189338180853b))
* **core:** announce every unit of work ([598b616](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/598b616b32d59c9a20a8be68bc305e45b2dfd962))
* **core:** log every request and response ([105c453](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/105c45362f85b47ad6e0fb70ed4cbb042180a43b))
* **core:** report the runtime of a running operation ([cdb1e5f](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/cdb1e5f72731ce1572564ec2cc6739be637dfb35))
* declared support for python 3.14 ([#9](https://github.com/peterschwps/SAP-Datasphere-CLI/issues/9)) ([bb38113](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/bb3811372de1e68cc98b9ad07f72bfcf6761e19c))
* exported public api ([8ff3464](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/8ff346474b77f460bbd1ff8a00764921e941386a))
* **logging:** make the level say what a line means ([2f9ec39](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/2f9ec39b854868db91c07cd646b1424e0116d061))
* **models:** report each result after model completion ([1733037](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/173303747c889422c1fc3ee61eaa3eb6321e4514))
* removed token persistence from the client ([79c42b2](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/79c42b2de394ce6ae8f71401a06c7df27e492122))
* **repository:** search the repository from one place ([740c5c1](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/740c5c154b8cb95aedcca038ea6a4c7b640eff83))
* restructured the client into endpoint and workflow layers ([#10](https://github.com/peterschwps/SAP-Datasphere-CLI/issues/10)) ([8a64dc6](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/8a64dc611095583ee6feddf9f45ced455b46ec70))
* **settings:** report a created settings file ([86680bf](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/86680bf019d62bf466311951308ad3cd96dc87d1))
* **task-chains:** report every chain as it finishes ([34e3c34](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/34e3c346df2a3e9b24ea0b73ade96a509380def7))
* took over session token persistence from the library ([d55c015](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/d55c015185bf6320218ac8a5de8adc0f9302bc5b))
* unified task input and per-run result folders ([b0a5c8b](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/b0a5c8b1d415afecfda39c97dd509dc4c205d236))
* **views:** compare analyzer scores with a minimum ([9e6fddd](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/9e6fddd3eefb0acd84ef0e6634ca38e4422d5b70))


### Bug Fixes

* **auth:** store only the refresh token ([a7e1c02](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/a7e1c02ea7bbdda58f34b0dc7f70193ea1420e2a))
* **cli:** propagate the return code with SystemExit ([a1b89a6](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/a1b89a6acf4e839df7e70d43f60ce4b8ce41748c))
* fix enter keypress sending input to menu after returning to it ([76ce451](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/76ce4515b074f65ccd021fcbd678267fb1622abe))
* fix typo in docstring ([ff26472](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/ff26472543202f000a1290e41227c1d280a9fc2f))
* fix wrong status being used when remote table does not have metadata ([2f670dc](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/2f670dc5e7d1acabfe3da149a0a580fcab1f64d7))
* fixed HTML tag error ([9953a4f](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/9953a4fdec04a7fa7e31da91d13afeef3184e397))
* removed __all__ ([8539650](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/853965005ce469d31bb5c12d02c372169e541331))
* removed doubled Datasphere folder in the Windows user dirs ([158270c](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/158270c7e782b04e7b86bb4d286c2fd087f66ad2))
* **repository:** ask the tenant for English type descriptions ([53fb82b](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/53fb82b3baa8ebb88d75310fe2637418fa177cc9))
* spelling mistakes ([7430cfc](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/7430cfc3437dedf9fddcc22a23bb99f0e7c29f12))
* **tui:** replace internal identifiers with more descriptive names ([2bb41a9](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/2bb41a90e5cf1d8c7e506531c42bc203e9ba35e0))
* **tui:** show a batch before its first item finishes ([91a2325](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/91a2325f02e4af2f02ab6f586bc0e2254525378d))
* use correct search word to filter for analytical models ([7c7cb82](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/7c7cb82f0b18221dd90f8e8e11f8da477386d7ec))
* **views:** refuse an unknown partitioning column ([48838ff](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/48838ff1a610c016c614376a727b7f2e1f32e7f3))
* **views:** treat the entered year as an exclusive upper bound ([eb11ae0](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/eb11ae00ca76b591bfd0849df3b4c90631e5ee03))


### Refactoring

* **actions:** call core commands directly instead of dispatching ([025724d](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/025724d6583479f4282755a6e8bb553dde55da2f))
* adapt import after renaming commands.py ([a15a35b](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/a15a35b47640445455eebd7d018a4d3731408058))
* add methods to BatchProgressState and implement StrEnums ([4a3f716](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/4a3f7166a64bfd1861cec7c9683c447a0f2a7056))
* adjust command definitions ([2524de2](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/2524de2474d155d71b252773dd7990ca5f16476f))
* adjust command definitions ([a217135](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/a21713577f115454c4927b611946267783341447))
* **analytical-models:** send the requests from the core ([800461e](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/800461eef2c7d3101b0b934cb39837cbe900ae97))
* centralized global methods for value conversion ([76e205f](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/76e205fa05a8b0eec993d83b66a460c8e3f5d56c))
* change name of import ([fa1c9c3](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/fa1c9c320a2826c2feda395bca2f196e2c03d4c2))
* changed import ([627cd94](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/627cd9405e748b2c389bbb11ca3a3f8746f1c786))
* changed imports after refactoring codebase ([e392409](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/e39240939afb4605033fbd6829fb74c738ff3483))
* **core:** group the modules by what they serve ([1eb17a0](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/1eb17a0f129c84364a7c0b23e3dc8eff9ec4d6d6))
* **core:** put the shared pieces where they belong ([27e87fc](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/27e87fc59323b01e9ff1d413b82c5be83e5d7f61))
* **core:** take over the session and drop the API package ([be4232f](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/be4232ff7ba75a262448b91d0c5a4f0346ad992b))
* implement Core command execution ([82f0884](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/82f0884ad0d7b721a032dd35ba4a3cbd899972f0))
* implement new execution logic ([6c44e72](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/6c44e7299b63c15ecb2de48d9a81e27850d0f08d))
* implement new execution logic ([86bd461](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/86bd461a34731640836e52d0b960158b662efe72))
* implement new execution logic ([898fb4b](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/898fb4b252c497678bbede6ebd66a30c4d96a45d))
* implemented new SessionConfig from datasphere-core package ([5cef59d](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/5cef59d736694b4db885d4ace212e437f125d4f1))
* implemented usage of the new BatchExecution class ([31e842c](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/31e842c46c2220b557f54aef21bc815466a95dae))
* improve error handling when measuring view ([5f08b82](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/5f08b82bd6363c056b19ccb3269d6e208c9dc220))
* **logging:** drop unused track_time decorator ([ef91ed8](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/ef91ed8ba63556204337c8891df857844e6bcdf5))
* merge CLI and MCP description into a single one ([d83d7f6](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/d83d7f6df8ec2eb75667e4ae1c5d7e6e913f3821))
* moved contents of static folder to different directories ([81fc5ef](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/81fc5ef020f8559915ffc0fa596309276c615071))
* moved from utils to root directory ([f759fb3](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/f759fb38b2c8281d681bfb682d2a534fd50766a6))
* moved images to docs folder ([d74a156](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/d74a156ab5ca39dfc028e09cdb0f1320c6b7e67f))
* moved logo and Textual CSS file to cli folder ([7d39ef3](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/7d39ef38457472930ad75cb3bdef958d33adb352))
* moved screens to cli folder ([971d722](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/971d722321c6af3ae2122f213f8470aefa4ba81b))
* reduce the client to transport ([#18](https://github.com/peterschwps/SAP-Datasphere-CLI/issues/18)) ([1046c63](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/1046c6322b8ec0a7af440ba00062d8451012fa3f))
* **remote-tables:** map the write outcome in the core ([62b9c10](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/62b9c1094f94d23c3425fac56d8ca56d010db6d1))
* **remote-tables:** send the requests from the core ([43cce9f](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/43cce9f2d17bf3f37902ff59dc9ad4476db3d331))
* remove dispatch_command function ([4f3e9f0](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/4f3e9f0214cb2a1d602308bf62caa66a1ac73278))
* remove test_concurrency.py test module as it is now implemented in test_execution.py ([88ca25f](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/88ca25fccffe16d935d2b9b05e64c1787ee03d2c))
* removed unneccesary validation logic from CommandDefinition ([66e1646](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/66e1646cc18fc79dce243d25d8206c671dbacc7a))
* rename *_sap_* variables ([37c0e0c](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/37c0e0c0e22ce74fb1cba8125b6afccf26a2b6e9))
* rename *_sap_* variables ([565855a](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/565855a07cc080417ecca99e604d2a0a38d3b76f))
* rename commands.py ([e1aca0c](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/e1aca0cb6eb93fffad25e3aa66198ae103eab1d9))
* renamed all operation_id references to log_id ([b2a16b2](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/b2a16b20b61d2b8d63667555f199f08343993d08))
* renamed argument for report method ([41feffc](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/41feffc31a09f9bc341e69fea9ffaed63bf8428c))
* renamed attribute of AnalyticalModelReference ([184dd1a](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/184dd1a0ad02477657814839670892e8778f4a0c))
* renamed cli.py to app and moved it to cli folder ([93ea1ec](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/93ea1ec149dbd4f122a5f2cd97ebe726df40a6e4))
* renamed CredentialStores to TokenStores ([5b31c78](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/5b31c78003685ef55651484b264b1fd6b957f86f))
* renamed direct.py to commands.py and moved to cli folder ([0c396c3](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/0c396c310822db754cf98d95db7d27c3227933f4))
* renamed to records.py and moved to files folder ([1c196c5](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/1c196c5f6bbb07383c4dd5a89f7ec4c6d10172e7))
* replaced DatasphereClient with DatasphereSession from new datasphere-core package ([4f45fb8](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/4f45fb8521fad8cf6a4ca6ddd1f0d36b3a6e9b39))
* simplify creation of ViewPersistenceCandidate ([32692ba](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/32692ba27f81e959748d89a03d3ca63c309a2482))
* split files.py and filehandler.py into different files ([4983fc7](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/4983fc74797b888e3170a313e2e346be2889e2cd))
* split up utils folder ([9f4fce6](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/9f4fce620508f959485fd3b76ca8de79e8d40b00))
* **task-chains:** own the run workflow in the core ([b479d6e](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/b479d6e2dc223304e4285263483aba893afc7697))
* **task-chains:** send the requests from the core ([9401c97](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/9401c979a1a5a150355f00ba6b22376da43600df))
* **task-chains:** use CommandContext and StartTaskChainRequest ([78ca220](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/78ca22005e415a27d26b3a228e44b8b8b1e63a6c))
* use more descriptive variable names and add explanatory comments ([750542e](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/750542e1cae0ba029e853d26ea204ceadd657329))
* **views:** own the partition creation in the core ([323b8bc](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/323b8bc739028286934ef2a502e5fc31df9cff21))
* **views:** own the partition lock logic in the core ([91a93e8](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/91a93e8fafaf480d8c562d255f52d1479f122c39))
* **views:** own the persistence workflows in the core ([c46b966](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/c46b96651e57952b827c184310912d62f6d651ab))
* **views:** own the view analyzer workflow in the core ([af92978](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/af92978502a0ee857f2904170c80788201f846a8))
* **views:** send the requests from the core ([7e12092](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/7e12092c12ed89fb760de57c9f4897b00576f7a0))


### Documentation

* adapt comments ([196c2ce](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/196c2ce1772e019c26ad9e49e9fbe43da9ecb5c8))
* add and fix docstrings ([c066379](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/c066379e645e6fe9b5f5c7bc3a9be07d9497f433))
* add comments and docstrings ([6129729](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/61297295592efe479311ffecc7abc7c50f3377a8))
* add docs explaining the architecture of the core ([7ec7c6b](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/7ec7c6b7a259b2f8345b6f5ce3a575c4db1f68cb))
* add docstrings to all classes ([78c4494](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/78c44942398e5e436f18e26eaf7e6bc635ef6e99))
* add explanatory comment ([0a65a6d](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/0a65a6d14ab6aa6b7bfa414c659cfcd288ab5a8b))
* add explanatory comment ([0cc8083](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/0cc8083aaca939224bc59fce67f699854394ec0a))
* add explanatory comments ([548384b](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/548384b69118b9aee1c314d60005092a06d2d1c9))
* add simple docstrings for each test ([6672cad](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/6672cadcfd06efea28abbf6e1acc4f8030f146f7))
* added collapsed sections for features ([7458350](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/7458350f6f1b39bdc257c37f3d8d2f2ba5f542ff))
* added docstrings to __init__ methods ([b63ebb9](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/b63ebb9d2554e0b2842badd429deccadd360f99b))
* added docstrings to DatasphereSession context manager methods ([9538099](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/953809956d43929153c1294b455802b6b506feb1))
* added docstrings to protocol methods ([05b53fc](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/05b53fc5396f4b8423b5b326b9abb508280e169d))
* added readme ([bdca6a1](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/bdca6a12e03f0b13696cc37f9ae4a473c2473b24))
* added readme badges ([76b11a4](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/76b11a4f941e989ed09c1744adb939a1cbd7fe52))
* added simple README ([5dafb4b](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/5dafb4b26f1df90e8cc060248e85c1e5e7920e86))
* adjusted readme badges ([38554fb](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/38554fb1d8bef564b8aa6afcdd52e8e3d48cd751))
* changed wording ([c9442d4](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/c9442d4990deb09b8a4e15d4d9c2366f638ade7f))
* complete docstrings and comments in the CLI layer ([44b21cb](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/44b21cbea45c0636498e9cc2b103e734df7884d4))
* correct two comments in the core ([100819f](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/100819f22632b92df9858eaacaf142a5b9415723))
* corrected settings, token and log file paths in the readme ([d288fd8](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/d288fd8f3294219d76d1e35b311231249eb73fc1))
* describe the HTTP logging ([1315a9a](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/1315a9a4223f6b8003ade9455b7382b042dfd3f0))
* describe the log levels ([81476ea](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/81476ea0de9cf90b00a7f8bdaac04748de29c3b7))
* fix table of content links ([634a272](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/634a272e50a2039fcc5444961c4d78571441dd8c))
* fixed docstrings ([f10cdf9](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/f10cdf95569d16cffbb098f8dae52e4db467ef7b))
* link developer guide ([7a8a748](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/7a8a748991c2245c5bfa4f6faa0d322f9df168a0))
* removed old windows installation and added more information about the new command layer ([ff48d55](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/ff48d55b0d45cd4c960d8fd873200d51d93026dd))
* removed redundant parts and structured features list ([138c5f1](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/138c5f1eade5e5b052950f5f1ba5a9e6bc2cfad7))
* **security:** add vulnerability reporting policy ([4bb049b](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/4bb049ba06dfa23f0bb80892c9e07c311e871b4f))
* update one-liner description ([9478a8b](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/9478a8b74d15f576ef553779b8511e953b434780))
* update README and core notes for the renamed log status ([3d92319](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/3d923196cb55b398a31b3821afa3f0df4229163b))
* updated cli repository link ([d7e6878](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/d7e6878937165d0675ade8677b015c8ebdf6c21d))


### Continuous Integration

* added release-please and pypi release pipeline ([68fad48](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/68fad48a8bca954082449dc15c9abc367c92dc5d))


### Misc

* set next release to 0.5.0 ([894a37b](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/894a37bc7a4c56642576260196a73020b6ac8ed1))

## [0.4.0](https://github.com/peterschwps/SAP-Datasphere-CLI/compare/v0.3.2...v0.4.0) (2026-07-08)


### ⚠ BREAKING CHANGES

* moved batch orchestration into the cli ([#21](https://github.com/peterschwps/SAP-Datasphere-CLI/issues/21))

### Features

* moved batch orchestration into the cli ([#21](https://github.com/peterschwps/SAP-Datasphere-CLI/issues/21)) ([fbecbd1](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/fbecbd1fc9e586761ed206739f640f8c8929d340))
* replaced the macos binary with a pypi installation ([#20](https://github.com/peterschwps/SAP-Datasphere-CLI/issues/20)) ([2677839](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/26778392580e6b07f9ea3b4a0f47bb928c405361))


### Refactoring

* moved the package to src layout as datasphere_cli ([#18](https://github.com/peterschwps/SAP-Datasphere-CLI/issues/18)) ([db9215d](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/db9215d558630e9db8938a2e284a628cd2246969))

## [0.3.2](https://github.com/peterschwps/SAP-Datasphere-CLI/compare/v0.3.1...v0.3.2) (2026-07-07)


### Features

* added support for python 3.14 ([#17](https://github.com/peterschwps/SAP-Datasphere-CLI/issues/17)) ([97971ce](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/97971ce78b1888fdad99452a30960a3c89317f70))
* packaged the macos release as a dmg ([#15](https://github.com/peterschwps/SAP-Datasphere-CLI/issues/15)) ([32c0f3d](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/32c0f3db8faf531d977a978aeba0f87893c9267c))


### Documentation

* adjusted readme badges ([be538b5](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/be538b582e152e470ffbbcf8600b7bba616692b1))

## [0.3.1](https://github.com/peterschwps/SAP-Datasphere-CLI/compare/v0.3.0...v0.3.1) (2026-07-07)


### Bug Fixes

* ran pyinstaller without local sources in release builds ([8c83302](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/8c83302ec3985bc863c210fb28ad8355bbd6485a))


### Documentation

* added readme badges and updated title ([b26e339](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/b26e3391148402d049683d091388a91557fee157))

## [0.3.0](https://github.com/peterschwps/SAP-Datasphere-CLI/compare/v0.2.1...v0.3.0) (2026-07-07)


### Features

* added file-backed action wrappers ([3316648](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/3316648a3fbd41c7ce7750ba606a53bb8604ae12))


### Refactoring

* made settings and logging setup explicit ([1df05ac](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/1df05ac66110ea3b6bd2c4204e4171ff812e75d1))
* moved the api layer into the datasphere-api library ([2ccdb52](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/2ccdb523e3fb3825170c585e6058d445c1ec78ab))
* ran menu actions through the datasphere-api client ([de3b47b](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/de3b47bca0e029f412f225cc2a9a5c5bc56b5724))
* removed embedded datasphere api layer ([65b3237](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/65b32373a24e00ce4aeab83d5049b27412b362b4))


### Continuous Integration

* added release-please and pypi release pipeline ([0ad3b9b](https://github.com/peterschwps/SAP-Datasphere-CLI/commit/0ad3b9bdef7175892baf46159c8864143c2c55b3))
