registerTemplate("web_editor.SnippetsMenu", `/web_editor/static/src/xml/snippets.xml`, `<t t-name="web_editor.SnippetsMenu" xml:space="preserve">
        <div id="oe_snippets" t-ref="snippets-menu" t-on-mousedown="_onMouseDown">
            <div class="o_we_website_top_actions">
                <div class="o_we_external_history_buttons d-flex">
                    <button type="button" t-on-click="_onUndo" class="btn btn-secondary fa fa-undo" t-att-disabled="!state.canUndo"/>
                    <button type="button" t-on-click="_onRedo" class="btn btn-secondary fa fa-repeat" t-att-disabled="!state.canRedo"/>
                </div>
                <form class="ms-auto d-flex">
                    <button type="button" t-on-click="_onDiscardClick" class="btn btn-secondary" data-action="cancel" title="Tip: Esc to preview" accesskey="j">Discard</button>
                    <button type="button" t-on-click="_onSaveRequest" class="btn btn-primary" data-action="save" accesskey="s">Save</button>
                </form>
            </div>
            <div id="snippets_menu">
                <button type="button" tabindex="1" t-on-click="_onBlocksTabClick" t-att-class="{ 'active': state.currentTab === constructor.tabs.BLOCKS }" class="o_we_add_snippet_btn text-uppercase" accesskey="1">
                    <span>Blocks</span>
                </button>
                <button type="button" tabindex="2" t-on-click="_onOptionsTabClick" t-att-class="{ 'active': state.currentTab === constructor.tabs.OPTIONS }" class="o_we_customize_snippet_btn text-uppercase">
                    <span>Customize</span>
                </button>
            </div>

            <div t-if="!this.hasSnippetGroups" class="o_snippet_search_filter" t-att-class="{ 'd-none': state.currentTab !== constructor.tabs.BLOCKS }">
                <input type="text" class="o_snippet_search_filter_input" t-ref="search-input" t-model="state.search" placeholder="Search for a block (e.g. numbers, image wall, ...)"/>
                <i role="button" class="fa fa-times o_snippet_search_filter_reset" t-att-class="{ 'd-none': state.search === ''}" t-on-click="() =&gt; state.search = ''"/>
            </div>

            <div id="o_scroll" t-ref="snippets-area" t-att-class="{ 'd-none': state.currentTab !== constructor.tabs.BLOCKS }">
                <t t-set="disabledTooltip">This block cannot be dropped anywhere on this page.</t>
                <t t-foreach="getSnippetsByCategories()" t-as="category" t-key="category.id">
                    <div t-att-id="category.id" t-if="category_value.length &gt; 0" class="o_panel">
                        <div class="o_panel_header">
                            <span t-esc="category.text"/>
                        </div>
                        <div t-att-id="category.id === 'snippet_custom' ? 'snippet_custom_body' : ''" class="o_panel_body" t-on-pointerup="_onMouseUp">
                            <t t-foreach="category_value" t-as="snippet" t-key="snippet.key">
                                <div t-if="snippet.visible" class="oe_snippet" t-att-class="{ 'o_disabled': snippet.disabled, 'o_snippet_install': snippet.installable, 'o_we_draggable': !snippet.renaming and !snippet.installable and !snippet.disabled }" t-att-name="snippet.displayName" t-att-data-oe-snippet-id="snippet.id" t-att-data-module-id="snippet.moduleId" t-att-data-module-display-name="snippet.moduleDisplayName" t-on-click="this._onSnippetClick" t-att-data-tooltip="snippet.disabled ? disabledTooltip : false" t-att-data-snippet-group="snippet.snippetGroup" t-att-data-snippet-key="snippet.key">
                                    <t t-if="snippet.disabled">
                                        <img src="/web_editor/static/src/img/snippet_disabled.svg" class="o_snippet_undroppable"/>
                                    </t>
                                    <div class="oe_snippet_thumbnail" t-att-class="{ 'o_we_ongoing_insertion': snippet.renaming }" t-att-data-snippet="snippet.baseBody.dataset.snippet">
                                        <div class="oe_snippet_thumbnail_img" t-attf-style="background-image: url({{snippet.thumbnailSrc}});"/>
                                        <t t-if="snippet.isCustom and snippet.renaming">
                                            <we-input class="o_we_user_value_widget w-100 mx-1">
                                                <div>
                                                    <input type="text" autocomplete="chrome-off" t-att-value="snippet.displayName" class="text-start"/>
                                                    <we-button class="o_we_confirm_btn o_we_text_success fa fa-check" data-tooltip="Confirm" t-on-click="_onConfirmRename"/>
                                                    <we-button class="o_we_cancel_btn o_we_text_danger fa fa-times" data-tooltip="Cancel" t-on-click="() =&gt; snippet.renaming = false"/>
                                                </div>
                                            </we-input>
                                        </t>
                                        <t t-else="">
                                            <span class="oe_snippet_thumbnail_title"><t t-out="snippet.displayName"/></span>
                                        </t>
                                        <t t-if="snippet.installable">
                                            <button class="btn btn-primary o_install_btn w-100" t-on-click="_onInstallBtnClick">Install</button>
                                        </t>
                                    </div>
                                    <t t-if="snippet.isCustom and !snippet.renaming">

                                        <we-button class="o_rename_btn fa fa-pencil btn o_we_hover_success" t-att-data-tooltip="snippet.renameTitle" t-att-data-snippet-key="snippet.key" t-on-click.stop="_onRenameBtnClick" t-on-pointerup.stop=""/>
                                        <we-button class="o_delete_btn fa fa-trash btn o_we_hover_danger" t-att-data-tooltip="snippet.deleteTitle" t-att-data-snippet-key="snippet.key" t-on-click.stop="_onDeleteBtnClick" t-on-pointerup.stop=""/>
                                    </t>
                                </div>
                            </t>
                        </div>
                    </div>
                </t>
            </div>
            <div class="o_we_customize_panel" t-ref="customize-panel" t-att-class="{ 'd-none': state.currentTab === constructor.tabs.BLOCKS }">
                <we-customizeblock-options id="o_we_editor_toolbar_container" t-att-class="{ 'd-none': !state.showToolbar }">
                    <we-title>
                        <span t-out="state.toolbarTitle"/>
                        <div id="removeFormat" data-call="removeFormat" title="Remove format" class="btn fa fa-eraser fa-fw"/>
                    </we-title>
                    <div class="o_we_toolbar_wrapper" t-ref="toolbar-wrapper" style="display: contents;">
                        <Toolbar t-props="options.wysiwyg.state.toolbarProps">
                            <t t-if="options.wysiwyg.state.linkToolProps">
                                <LinkTools t-props="options.wysiwyg.state.linkToolProps"/>
                            </t>
                        </Toolbar>
                    </div>
                </we-customizeblock-options>
                <t t-call="web_editor.toolbar.table-options"/>
            </div>
            <div t-if="state.invisibleElements.length" class="o_we_invisible_el_panel">
                <div class="o_panel_header">
                    Invisible Elements
                </div>
                <t t-foreach="state.invisibleElements" t-as="invisibleEntry" t-key="invisibleEntry_index">
                    <t t-call="web_editor.invisibleSnippetEntry" t-call-context="{'entry': invisibleEntry, 'menu': this}"/>
                </t>
            </div>
        </div>
    </t>

    `);