"""Keep device credentials in QGIS Authentication Manager, never QgsSettings."""
from __future__ import annotations


AUTHCFG_SETTING = 'geonod/authentication_config_id'


class QgisCredentialStore:
    def __init__(self):
        self._memory_credential = None

    def save(self, credential: str) -> None:
        from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings
        config = QgsAuthMethodConfig()
        config.setName('GeoNod device credential')
        config.setMethod('Basic')
        config.setConfig('username', 'geonod-device')
        config.setConfig('password', credential)
        manager = QgsApplication.authManager()
        if not manager.storeAuthenticationConfig(config):
            # An unopened authentication database must not tempt us to save a
            # bearer credential in normal settings. Keep it only this session.
            self._memory_credential = credential
            return
        QgsSettings().setValue(AUTHCFG_SETTING, config.id())
        self._memory_credential = None

    def read(self) -> str | None:
        from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings
        config_id = str(QgsSettings().value(AUTHCFG_SETTING, '') or '')
        if config_id:
            config = QgsAuthMethodConfig()
            if QgsApplication.authManager().loadAuthenticationConfig(config_id, config, True):
                credential = str(config.config('password') or '').strip()
                if credential:
                    return credential
        return self._memory_credential

    def delete(self) -> None:
        from qgis.core import QgsApplication, QgsSettings
        settings = QgsSettings()
        config_id = str(settings.value(AUTHCFG_SETTING, '') or '')
        if config_id:
            QgsApplication.authManager().removeAuthenticationConfig(config_id)
        settings.remove(AUTHCFG_SETTING)
        self._memory_credential = None
