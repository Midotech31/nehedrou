"""Plain-text media choice labels; no storage access or qualification decision."""


def media_choice_label(asset):
    """Show a basename, short record ID and the existing localised rights status."""
    name = str(asset.file.name or '').replace('\\', '/')
    basename = name.rsplit('/', 1)[-1]
    return f"{basename} · {str(asset.pk)[:8]} · {asset.get_rights_status_display()}"
