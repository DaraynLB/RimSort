"""Dialog for browsing and comparing mod list history snapshots."""

from collections.abc import Callable

from loguru import logger
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.modlist_history_service import (
    KeptEntry,
    ModListDiff,
    ModlistHistoryService,
    NotedEntry,
    Snapshot,
    SnapshotEntry,
)
from app.utils.generic import open_url_browser, platform_specific_open
from app.views import dialogue


class ModlistHistoryPanel(QDialog):
    """Lists mod list snapshots for the current instance and diffs any two."""

    def __init__(
        self,
        history_service: ModlistHistoryService,
        restore_callback: Callable[[list[str]], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("modlistHistoryPanel")
        self.setWindowTitle(self.tr("Mod List History"))
        self._service = history_service
        self._restore_callback = restore_callback
        self._snapshots: list[Snapshot] = []

        self._setup_ui()
        self.resize(1000, 620)
        self._reload()

    # ------------------------------------------------------------------ setup
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        description = QLabel(
            self.tr(
                "Every save writes a snapshot of your mod list. Select a snapshot "
                "to compare it with the one before it, or hold Ctrl and select two "
                "snapshots to compare them directly."
            )
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter, stretch=1)

        self.snapshot_list = QListWidget()
        self.snapshot_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.snapshot_list.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.snapshot_list)

        self.diff_panel = QWidget()
        diff_layout = QVBoxLayout(self.diff_panel)
        diff_layout.setContentsMargins(0, 0, 0, 0)

        self.comparing_label = QLabel()
        self.comparing_label.setWordWrap(True)
        diff_layout.addWidget(self.comparing_label)

        columns_layout = QHBoxLayout()
        diff_layout.addLayout(columns_layout, 1)
        self.added_header, self.added_tree = self._make_diff_column(columns_layout)
        self.kept_header, self.kept_tree = self._make_diff_column(columns_layout)
        self.removed_header, self.removed_tree = self._make_diff_column(columns_layout)
        for tree in (self.added_tree, self.kept_tree, self.removed_tree):
            tree.itemClicked.connect(self._on_diff_item_clicked)
            tree.setMouseTracking(True)
            tree.itemEntered.connect(self._on_diff_item_hovered)

        splitter.addWidget(self.diff_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        button_row = QHBoxLayout()

        self.restore_button = QPushButton(self.tr("Restore Selected"))
        self.restore_button.setObjectName("actionButton")
        self.restore_button.clicked.connect(self._on_restore)
        button_row.addWidget(self.restore_button)

        self.export_button = QPushButton(self.tr("Export Selected…"))
        self.export_button.clicked.connect(self._on_export)
        button_row.addWidget(self.export_button)

        self.note_button = QPushButton(self.tr("Edit Note…"))
        self.note_button.clicked.connect(self._on_edit_note)
        button_row.addWidget(self.note_button)

        button_row.addStretch()

        open_folder_button = QPushButton(self.tr("Open History Folder"))
        open_folder_button.clicked.connect(self._on_open_folder)
        button_row.addWidget(open_folder_button)

        close_button = QPushButton(self.tr("Close"))
        close_button.clicked.connect(self.close)
        button_row.addWidget(close_button)

        layout.addLayout(button_row)

    @staticmethod
    def _make_diff_column(parent_layout: QHBoxLayout) -> tuple[QLabel, QTreeWidget]:
        """Build one "Added"/"Kept"/"Removed" column: a header label over a
        plain, read-only two-column list (mod name, optional note).

        The note gets its own column rather than being appended to the mod
        name in one string — that reads as clutter once a mod can carry a
        note like "deactivated" or "moved #12 → #45".
        """
        container = QVBoxLayout()
        header = QLabel()
        header.setObjectName("diffColumnHeader")
        container.addWidget(header)
        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setColumnCount(2)
        tree.setRootIsDecorated(False)
        tree.setIndentation(0)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tree.header().setStretchLastSection(False)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        container.addWidget(tree, 1)
        wrapper = QWidget()
        wrapper.setLayout(container)
        parent_layout.addWidget(wrapper, 1)
        return header, tree

    # ------------------------------------------------------------------ data
    def _reload(self) -> None:
        self._snapshots = self._service.list_snapshots()
        self.snapshot_list.clear()
        for index, snap in enumerate(self._snapshots):
            note = f"  —  {snap.note}" if snap.note else ""
            text = (
                f"{snap.display_timestamp}   "
                f"{len(snap.active)} active / {len(snap.inactive)} inactive   "
                f"[{snap.short_id}]{note}"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.snapshot_list.addItem(item)

        self._update_buttons()
        if self._snapshots:
            self.snapshot_list.setCurrentRow(0)
        else:
            self._clear_diff_columns()
            self.comparing_label.setText(
                self.tr("No snapshots yet — save your mod list to create one.")
            )

    def _selected_indices(self) -> list[int]:
        indices = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self.snapshot_list.selectedItems()
        ]
        return sorted(int(i) for i in indices)

    def _selected_pair(self) -> tuple[Snapshot, Snapshot] | None:
        """Return (older, newer) snapshots to diff, or None."""
        indices = self._selected_indices()
        if len(indices) >= 2:
            older = self._snapshots[indices[-1]]
            newer = self._snapshots[indices[0]]
            return older, newer
        if len(indices) == 1:
            newer = self._snapshots[indices[0]]
            if indices[0] + 1 < len(self._snapshots):
                older = self._snapshots[indices[0] + 1]
                return older, newer
        return None

    # --------------------------------------------------------------- events
    def _on_selection_changed(self) -> None:
        self._update_buttons()
        self._clear_diff_columns()

        pair = self._selected_pair()
        if pair is None:
            indices = self._selected_indices()
            if len(indices) == 1:
                self.comparing_label.setText(
                    self.tr("Oldest snapshot — nothing to compare against.")
                )
            return

        older, newer = pair
        try:
            diff = self._service.diff(older, newer)
        except Exception:
            logger.exception("Failed to diff mod list snapshots")
            return
        self._render_diff(older, newer, diff)

    def _clear_diff_columns(self) -> None:
        self.comparing_label.clear()
        for header, tree in (
            (self.added_header, self.added_tree),
            (self.kept_header, self.kept_tree),
            (self.removed_header, self.removed_tree),
        ):
            header.clear()
            tree.clear()

    def _render_diff(self, older: Snapshot, newer: Snapshot, diff: ModListDiff) -> None:
        self.comparing_label.setText(
            self.tr("Comparing {old} → {new}").format(
                old=older.display_timestamp, new=newer.display_timestamp
            )
        )

        if diff.is_empty:
            self.added_header.setText(self.tr("Added (0)"))
            self.kept_header.setText(self.tr("Kept the same (0)"))
            self.removed_header.setText(self.tr("Removed (0)"))
            self.kept_tree.addTopLevelItem(QTreeWidgetItem([self.tr("No differences")]))
            return

        self._fill_diff_column(
            self.added_header,
            self.added_tree,
            self.tr("Added ({n})"),
            diff.added,
            self.tr("activated"),
        )
        self._fill_kept_column(diff.kept)
        self._fill_diff_column(
            self.removed_header,
            self.removed_tree,
            self.tr("Removed ({n})"),
            diff.removed,
            self.tr("deactivated"),
        )

    def _fill_diff_column(
        self,
        header: QLabel,
        tree: QTreeWidget,
        title_template: str,
        entries: list[NotedEntry],
        pre_existing_note: str,
    ) -> None:
        """Fill an Added/Removed column.

        ``pre_existing_note`` labels entries where the mod already existed in
        the other snapshot and just crossed the active/inactive boundary
        (e.g. "activated"/"deactivated"); a plain install/uninstall gets no
        note, since the column itself already says what happened.
        """
        header.setText(title_template.format(n=len(entries)))
        for noted in entries:
            note = pre_existing_note if noted.pre_existing else ""
            item = QTreeWidgetItem([noted.entry.label, note])
            self._style_entry_item(item, noted.entry)
            tree.addTopLevelItem(item)

    def _fill_kept_column(self, kept: list[KeptEntry]) -> None:
        """Fill the "Kept the same" column: every mod whose active/inactive
        membership didn't change, with a note for the ones reordered within
        the active list.
        """
        self.kept_header.setText(self.tr("Kept the same ({n})").format(n=len(kept)))
        for kept_entry in kept:
            note = ""
            if kept_entry.old_position is not None:
                note = self.tr("moved #{old} → #{new}").format(
                    old=kept_entry.old_position, new=kept_entry.new_position
                )
            item = QTreeWidgetItem([kept_entry.entry.label, note])
            self._style_entry_item(item, kept_entry.entry)
            self.kept_tree.addTopLevelItem(item)

    def _style_entry_item(self, item: QTreeWidgetItem, entry: SnapshotEntry) -> None:
        """Attach the package id / source to the tooltip, and turn the mod
        name into a clickable Steam Workshop link when it has one.

        The package id used to be concatenated onto the visible name; it
        lives in the tooltip now so the row stays readable.
        """
        tooltip_lines = [self.tr("Package ID: {pid}").format(pid=entry.package_id)]
        if entry.source and entry.source != "unknown":
            tooltip_lines.append(self.tr("Source: {src}").format(src=entry.source))
        workshop_url = entry.workshop_url
        if workshop_url:
            tooltip_lines.append(self.tr("Click to open Workshop page"))
            font = item.font(0)
            font.setUnderline(True)
            item.setFont(0, font)
            item.setForeground(0, QColor("#4EA6ED"))
        item.setToolTip(0, "\n".join(tooltip_lines))
        item.setData(0, Qt.ItemDataRole.UserRole, workshop_url)

    def _on_diff_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        url = item.data(0, Qt.ItemDataRole.UserRole)
        if url:
            open_url_browser(url)

    @staticmethod
    def _on_diff_item_hovered(item: QTreeWidgetItem, column: int) -> None:
        """Show a pointing-hand cursor only over rows with a Workshop link."""
        tree = item.treeWidget()
        if tree is None:
            return
        has_url = bool(item.data(0, Qt.ItemDataRole.UserRole))
        tree.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor if has_url else Qt.CursorShape.ArrowCursor
        )

    def _update_buttons(self) -> None:
        one_selected = len(self._selected_indices()) == 1
        self.restore_button.setEnabled(one_selected)
        self.export_button.setEnabled(one_selected)
        self.note_button.setEnabled(one_selected)

    def _current_snapshot(self) -> Snapshot | None:
        indices = self._selected_indices()
        if len(indices) != 1:
            return None
        return self._snapshots[indices[0]]

    # --------------------------------------------------------------- actions
    def _on_restore(self) -> None:
        snap = self._current_snapshot()
        if snap is None:
            return
        confirmed = dialogue.show_dialogue_conditional(
            title=self.tr("Restore Mod List"),
            text=self.tr("Load the active mod list from this snapshot ({ts})?").format(
                ts=snap.display_timestamp
            ),
            information=self.tr(
                "This replaces the mods currently loaded in RimSort. Nothing is "
                "written to disk until you press Save."
            ),
            button_text_override=[self.tr("Restore")],
        )
        if confirmed != self.tr("Restore"):
            return
        try:
            self._restore_callback(list(snap.active_package_ids))
        except Exception:
            logger.exception("Failed to restore mod list snapshot")
            dialogue.show_warning(
                title=self.tr("Restore failed"),
                text=self.tr("Could not restore the selected snapshot."),
            )
            return
        self.close()

    def _on_export(self) -> None:
        snap = self._current_snapshot()
        if snap is None:
            return
        target = dialogue.show_dialogue_file(
            mode="save",
            caption=self.tr("Export snapshot"),
            _dir=f"{snap.timestamp}__{snap.short_id}.json",
            _filter="JSON (*.json)",
        )
        if not target:
            return
        try:
            destination = target if target.endswith(".json") else target + ".json"
            with (
                open(snap.path, "r", encoding="utf-8-sig") as src,
                open(destination, "w", encoding="utf-8") as dst,
            ):
                dst.write(src.read())
        except OSError:
            logger.exception("Failed to export mod list snapshot")
            dialogue.show_warning(
                title=self.tr("Export failed"),
                text=self.tr("Could not write the snapshot file."),
            )

    def _on_edit_note(self) -> None:
        snap = self._current_snapshot()
        if snap is None:
            return
        note, ok = QInputDialog.getMultiLineText(
            self,
            self.tr("Snapshot Note"),
            self.tr("Note for {ts}:").format(ts=snap.display_timestamp),
            snap.note,
        )
        if not ok:
            return
        try:
            self._service.set_note(snap.path, note.strip())
        except (OSError, ValueError):
            logger.exception("Failed to write snapshot note")
            dialogue.show_warning(
                title=self.tr("Could not save note"),
                text=self.tr("The snapshot note could not be written."),
            )
            return
        self._reload()

    def _on_open_folder(self) -> None:
        platform_specific_open(str(self._service.history_dir()))
