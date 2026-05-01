<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.16" styleCategories="Symbology">
  <pipe>
    <rasterrenderer type="singlebandpseudocolor" band="1" opacity="1" alphaBand="-1" classificationMin="-100" classificationMax="999">
      <rastershader>
        <colorrampshader colorRampType="DISCRETE" classificationMode="1" clip="0">
          <item alpha="255" value="-100" label="Derin vadi / çukur" color="#2166ac"/>
          <item alpha="255" value="-40" label="Vadi tabanı" color="#74add1"/>
          <item alpha="255" value="-10" label="Alt yamaç" color="#d1e5f0"/>
          <item alpha="255" value="10" label="Düz / orta konum" color="#f7f7f7"/>
          <item alpha="255" value="40" label="Üst yamaç" color="#fddbc7"/>
          <item alpha="255" value="100" label="Sırt" color="#ef8a62"/>
          <item alpha="255" value="999" label="Keskin tepe" color="#b2182b"/>
        </colorrampshader>
      </rastershader>
    </rasterrenderer>
  </pipe>
</qgis>
