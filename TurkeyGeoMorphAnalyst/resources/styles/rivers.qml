<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.16" styleCategories="Symbology">
  <renderer-v2 type="categorizedSymbol" attr="waterway" symbollevels="0" enableorderby="0">
    <categories>
      <category value="river" label="Nehir" symbol="0" render="true"/>
      <category value="stream" label="Dere" symbol="1" render="true"/>
      <category value="canal" label="Kanal" symbol="2" render="true"/>
      <category value="drain" label="Drenaj kanalı" symbol="3" render="true"/>
      <category value="tidal_channel" label="Gelgit kanalı" symbol="4" render="true"/>
    </categories>
    <symbols>
      <symbol type="line" name="0" alpha="1" clip_to_extent="1"><layer class="SimpleLine" locked="0"><prop k="line_color" v="0,102,204,255"/><prop k="line_width" v="2.0"/><prop k="line_width_unit" v="MM"/></layer></symbol>
      <symbol type="line" name="1" alpha="1" clip_to_extent="1"><layer class="SimpleLine" locked="0"><prop k="line_color" v="68,153,221,255"/><prop k="line_width" v="0.8"/><prop k="line_width_unit" v="MM"/></layer></symbol>
      <symbol type="line" name="2" alpha="1" clip_to_extent="1"><layer class="SimpleLine" locked="0"><prop k="line_color" v="0,107,107,255"/><prop k="line_style" v="dash"/><prop k="line_width" v="1.5"/><prop k="line_width_unit" v="MM"/></layer></symbol>
      <symbol type="line" name="3" alpha="1" clip_to_extent="1"><layer class="SimpleLine" locked="0"><prop k="line_color" v="122,175,206,255"/><prop k="line_width" v="0.5"/><prop k="line_width_unit" v="MM"/></layer></symbol>
      <symbol type="line" name="4" alpha="1" clip_to_extent="1"><layer class="SimpleLine" locked="0"><prop k="line_color" v="0,51,102,255"/><prop k="line_width" v="1.2"/><prop k="line_width_unit" v="MM"/></layer></symbol>
    </symbols>
  </renderer-v2>
</qgis>
